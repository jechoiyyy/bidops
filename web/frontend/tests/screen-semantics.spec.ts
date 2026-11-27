import { expect, test } from "@playwright/test";
import {
  mockOpportunity,
  mockPreSpecAutoDetail,
  mockPreSpecMatrix,
  mockWorkload,
  openProcessSection,
  settleProcessSection,
} from "./api-mock";
import { installScreenFixtures } from "./screen-fixtures";
import fixtures from "./fixtures/api.json" with { type: "json" };

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

// 오늘 할 일(2026-11-27 시안 C2): 요약 줄 세 칸은 한 줄이고,
// 건수를 못 받은 칸은 0이 아니라 `미확인`이다.
test("대시보드 요약 줄은 한 줄이고 칸 이름이 잘리지 않으며 확인 중으로 멈추지 않는다", async ({ page }) => {
  await mockWorkload(page, { generated_at: "2026-09-01T09:00:00Z", items: [
    { key: "order_plan_pending", count: 24, unavailable_reason: null },
    { key: "pre_spec_actionable", count: null, unavailable_reason: "provider_absent" },
    { key: "pre_spec_needs_check", count: null, unavailable_reason: "provider_absent" },
    { key: "tracking_action_required", count: null, unavailable_reason: "no_completed_execution" },
    { key: "tracking_hold_review_due", count: 2, unavailable_reason: null },
    { key: "bid_final_decision_pending", count: null, unavailable_reason: null },
    { key: "tracking_deadline_imminent", count: 4, unavailable_reason: null },
    { key: "human_check_required", count: 5, unavailable_reason: null },
    { key: "overview_human_review", count: 2, unavailable_reason: null },
    { key: "blocking_items_open", count: 3, unavailable_reason: null },
    { key: "order_plan_new_priority", count: 6, unavailable_reason: null },
  ] });
  await page.goto(`/?run=${encodeURIComponent(RUN_ID)}`);
  const cells = page.locator(".dash-summary-cell");
  await expect(cells).toHaveCount(3);
  await expect(page.locator(".dash-page a[data-count]").filter({ hasText: "확인 중" })).toHaveCount(0);
  const tops = await cells.evaluateAll(items => items.map(item => Math.round(item.getBoundingClientRect().top)));
  expect(new Set(tops).size).toBe(1);
  const clipped = await page.locator(".dash-summary-title").evaluateAll(labels => labels
    .filter(label => label.scrollWidth - label.clientWidth > 1).map(label => label.textContent));
  expect(clipped).toEqual([]);
});

test("흡수한 마감·감사 경로가 기존 쿼리를 보존한다", async ({ page }) => {
  // docs/design/PLAN.md (git 이력) 2단계: 마감 추적은 검토 대기열의 저장된 뷰, 산출물 감사
  // 감사 로그는 실행 상태 구역의 직접 진입 주소이므로
  // 경로가 그대로 남고, 담당자가 들고 온 쿼리를 잃지 않아야 한다.
  await page.goto(`/deadlines?run=${encodeURIComponent(RUN_ID)}&from=dashboard`);
  // 전체 실행에서 400여 개가 동시에 붙으면 기본 5초 안에 이동이 끝나지 않아
  // 화면 결함 없이 깨졌다. 여유를 늘려 부하와 회귀를 구분한다.
  await expect.poll(() => new URL(page.url()).searchParams.get("sort"), { timeout: 15_000 }).toBe("deadline");
  let params = new URL(page.url()).searchParams;
  expect(params.get("run")).toBe(RUN_ID);
  expect(params.get("from")).toBe("dashboard");
  // `/deadlines` keeps the queue view but uses its shared route metadata, whose
  // location row keeps the screen name after an active notice owns the heading.
  await expect(page.locator("header.topbar .topbar-location-title")).toHaveText("공고 판정 이력");

  await page.goto(`/audit?run=${encodeURIComponent(RUN_ID)}&from=review`);
  await expect(page.locator("header.topbar h1")).toHaveText("실행 상태");
  await expect(page.getByRole("navigation", { name: "실행 상태 구역" }).getByRole("link", { name: "산출물 감사 로그", exact: true })).toHaveAttribute("aria-current", "page");
  params = new URL(page.url()).searchParams;
  expect(params.get("run")).toBe(RUN_ID);
  expect(params.get("from")).toBe("review");
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
  await expect(page.getByText("미확인 항목이 없어요. · 0건", { exact: true })).toHaveCount(0);
});

test("프로필 읽기 실패는 빈 정상 상태가 아니라 오류 상태로 표시한다", async ({ page }) => {
  await page.route("**/api/profile/sections", async (route) => {
    await route.fulfill({
      status: 500,
      contentType: "application/json",
      body: JSON.stringify({ detail: "프로필 원문을 읽을 수 없어요." }),
    });
  });

  await page.goto("/profile");
  const error = page.getByRole("alert").filter({ hasText: "판정용 프로필 사본을 불러오지 못했어요" });
  await expect(error).toBeVisible();
  await expect(error).toContainText("프로필 사본의 구조화 항목과 미확인 건수를 조회할 수 없어요.");
  await expect(error.getByRole("button", { name: "다시 조회" })).toBeVisible();
  await expect(page.getByText("승인된 판정용 프로필 사본이 없어요", { exact: true })).toHaveCount(0);
});

test("진행 중인 전량 판정은 중복 실행할 수 없다", async ({ page }) => {
  await page.goto(`/runs?run=${encodeURIComponent(RUN_ID)}`);
  await expect(page.getByRole("heading", { name: "전체 후보 판정 실행" })).toBeVisible();
  await expect(page.getByRole("button", { name: "전량 판정 대기열에 넣기" })).toBeDisabled();
  await expect(page.getByText("진행 중인 전량 판정 실행이 있어 새 실행을 시작할 수 없어요.")).toBeVisible();
});

test("정책 활성화는 최신 운영 게이트와 담당자 없이는 열리지 않는다", async ({ page }) => {
  await page.goto(`/policies?policy=${CANDIDATE_POLICY}&ptab=approval`);
  const activate = page.getByRole("group", { name: "결정 영역", exact: true }).getByRole("button", { name: "정책 활성화 확인" });
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
  await expect(page.getByText("상시 운영이 거부되었어요")).toBeVisible();
  await expect(page.getByRole("alert", { name: "상시 운영 켜기 차단 사유" })).toContainText("켤 수 없는 상태예요");
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

// docs/design/PLAN.md (git 이력) 3단계: 사전규격 목록에서 심층 추적 승인 패널을 연 상태는
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
  "심층 검토 시작됨",
  "개요 검토 종료",
  "자동 준비 중단",
];

const GRADE_LABELS = ["우선 검토", "검토 권장", "관찰 대상", "제외", "판정 없음"];

async function leafGradeTexts(page: import("@playwright/test").Page, scope: string): Promise<string[]> {
  return page.evaluate(([selector, labels]) => [...document.querySelectorAll<HTMLElement>(`${selector} *`)]
    .filter((element) => element.children.length === 0)
    .map((element) => (element.textContent ?? "").trim())
    .filter((text) => (labels as string[]).includes(text)), [scope, GRADE_LABELS] as const);
}

// 2026-11-19(사전규격 단계 수정안 §3 B): C-1 공고 판정을 다시 돌리지 않으므로 사전규격 화면은
// 등급을 그리지 않는다. 자동 준비 8값은 문자로 남는다(상세 필터의 선택지와 상세 ⑥).
test("사전규격 선택 상세는 등급을 그리지 않고 자동 준비 8값은 문자로 남는다", async ({ page }) => {
  await mockPreSpecMatrix(page);
  await page.goto("/pre-specs");
  const rows = page.locator(".pre-specs-row");
  await expect(rows).toHaveCount(8);
  for (let index = 0; index < AUTO_PREPARATION_LABELS.length; index += 1) {
    await rows.filter({ hasText: `자동 준비 표본 ${index + 1}` }).click();
    await expect(page.locator(".pre-specs-detail-title")).toContainText(`자동 준비 표본 ${index + 1}`);
    expect(await leafGradeTexts(page, ".pre-specs-detail-pane")).toEqual([]);
  }
  await page.getByRole("button", { name: "상세 필터", exact: true }).click();
  await expect(page.getByRole("combobox", { name: /적합성 등급/ })).toHaveCount(0);
  await page.getByRole("combobox", { name: "자동 준비 상태" }).click();
  for (const label of AUTO_PREPARATION_LABELS) {
    await expect(page.getByRole("option", { name: label, exact: true })).toBeVisible();
  }
});

test("사전규격 상세가 자동 준비 세 단계를 한 줄로 말하고 기존 심층 검토 동선이 없다", async ({ page }) => {
  await mockPreSpecAutoDetail(page, "started");
  await page.goto("/pre-specs/991");

  // 2026-11-21: 자동 준비 단계는 맨 아래 접힌 `처리 상태·기술 정보` 안에 있다. 확정 묶음·개요 완료 건은 닫혀 들어온다.
  await expect(await settleProcessSection(page)).toHaveAttribute("aria-expanded", "false");
  await expect(page.locator(".pre-spec-auto-steps")).toHaveCount(0);
  await openProcessSection(page);
  const steps = page.locator("#ps-process .pre-spec-auto-steps");
  await expect(steps).toBeVisible({ timeout: 10_000 });
  await expect(page.locator(".pre-spec-detail-grade-row")).toHaveCount(0);
  await expect(steps).toContainText("1 · 첨부 취득");
  await expect(steps).toContainText("완료 2 · 대기 1 · 진행 0 · 차단 0 · 실패 0");
  await expect(steps).toContainText("2 · 문서 묶음");
  await expect(steps).toContainText("확정 완료");
  await expect(steps).toContainText("3 · 개요 검토");
  await expect(steps).not.toContainText("4 · 심층 검토");
  await expect(page.getByRole("link", { name: /실행·보고서 열기|심층 검토 보고서 열기/ })).toHaveCount(0);
  await expect(page.locator('a[href^="/deep-reviews/"]')).toHaveCount(0);
});

test("개요가 끝난 확정 묶음은 개요 검토 종료로 말하고 심층 검토 실행 동선을 주지 않는다", async ({ page }) => {
  await mockPreSpecAutoDetail(page, "settled");
  await page.goto("/pre-specs/991");

  await openProcessSection(page);
  const steps = page.locator("#ps-process .pre-spec-auto-steps");
  await expect(steps).toBeVisible({ timeout: 10_000 });
  await expect(page.locator(".ps-document-panel-summary-line")).toContainText("개요 검토 종료");
  await expect(page.getByText("심층 검토 클릭 대기", { exact: false })).toHaveCount(0);
  await expect(page.getByRole("link", { name: /심층 검토 실행/ })).toHaveCount(0);
  await expect(page.locator('a[href="#document-preparation"]')).toHaveCount(0);
});

// 명세 §6.2의 "현재 등급 하나" 규칙은 2026-11-19에 "등급 없음"으로 바뀌었다 — 사람 정정 등급이
// 있어도 사전규격 상세는 등급을 그리지 않는다. 문서 준비 패널은 실제 자격 문장을 보인다.
test("사전규격 상세는 정정 등급이 있어도 등급을 그리지 않고 실제 자격 문장을 보인다", async ({ page }) => {
  await mockPreSpecAutoDetail(page, "corrected");
  await page.goto("/pre-specs/991");
  await openProcessSection(page);
  const toggle = page.getByRole("button", { name: /^문서 준비 (열기|닫기)$/ });
  await expect(toggle).toBeVisible({ timeout: 10_000 });
  if ((await toggle.textContent())?.includes("열기")) await toggle.click();
  await expect(page.locator("#document-preparation")).toBeVisible();

  expect(await leafGradeTexts(page, "body")).toEqual([]);
  await expect(page.getByText("화면 참고 등급", { exact: false })).toHaveCount(0);
  await expect(page.locator(".document-preparation-gate")).toContainText("자격을 다시 확인");
});

test("자동 심층 검토가 있어도 사업 추적 화면은 미선택을 그대로 보여준다", async ({ page }) => {
  await mockOpportunity(page);
  // §7.2: `미선택`은 더 이상 `조치 필요`(기본 탭)에 들지 않는다(`신규 입찰공고`·
  // `미결정`으로만 간다). `전체`로 이동해 `미선택` 표시가 여전히 그대로인지 본다.
  await page.goto("/opportunities?section=%EC%A0%84%EC%B2%B4");
  await expect(page.locator("header.topbar h1")).toHaveText("사업기회", { timeout: 10_000 });
  await expect(page.getByText("미선택").first()).toBeVisible();
  // 자동 심층 검토를 위한 새 구역을 만들지 않는다.
  await expect(page.getByText("자동 심층 검토", { exact: false })).toHaveCount(0);
});

// F2 · spec §6.3 — 입찰공고 상세의 금액 두 칸·개찰·유사 실적.
//
// 원문 `budget`은 배정예산 → 추정가격 → 기초금액 순으로 채워진 값이므로
// ('배정예산'이 아니다) `추정가격`과 **값이 같아도 한 칸으로 합치지 않는다**.
// 개찰일시는 `lifecycle.opening_at`이고 값이 없는 회차에는 키 자체가 없다.
// 유사 실적은 출처가 둘이며(수집 탐색 신호·판정 검토 결과) 구조가 달라 표를
// 나눈다 — 비어 있으면 `대조된 실적 없음`이다.
async function noticeFacts(page: import("@playwright/test").Page): Promise<Record<string, string>> {
  return page.locator(".notice-record-facts").evaluate((list) => {
    const entries: Record<string, string> = {};
    for (const label of list.querySelectorAll("dt")) {
      entries[(label.textContent ?? "").trim()] = (label.nextElementSibling?.textContent ?? "").trim();
    }
    return entries;
  });
}

test("입찰공고 상세는 예산과 추정가격을 따로 두고 개찰 없음과 대조된 실적 없음을 구분한다", async ({ page }) => {
  await page.goto(`/judgments/29?run=${encodeURIComponent(RUN_ID)}`);
  await expect(page.locator(".notice-record-facts")).toBeVisible({ timeout: 10_000 });

  const facts = await noticeFacts(page);
  // 서로 다른 두 값이 각자의 칸에 남는다.
  expect(facts["예산 (원문 제공 금액)"]).toBe("182,050,000원");
  expect(facts["추정가격"]).toBe("165,500,000원");
  // 이 회차 snapshot에는 `opening_at` 키가 없다(적재기가 null을 넣지 않는다).
  expect(facts["개찰"]).toBe("미제공");
  // R3가 고친 지역 제한 표기는 그대로다.
  expect(facts["지역·참가제한"]).toContain("지역 제한 미확인");

  const performance = page.locator(".performance-matches-panel");
  await expect(performance.getByRole("heading", { name: "유사 실적 · 회사 실적과 대조" })).toBeVisible();
  // 두 출처가 모두 비었으면 한 번만 말한다. 실제 0인 최고 유사도를 값 없음으로 바꾸지 않는다.
  await expect(performance.getByText("대조된 실적 없음")).toHaveCount(1);
  await expect(performance.locator(".panel-note")).toHaveText("최고 유사도 0.00");
  await expect(performance.locator("table")).toHaveCount(0);
});

test("유사 실적은 수집 탐색 신호와 판정 검토 결과를 따로 두고 예산·추정가격이 같아도 두 칸이다", async ({ page }) => {
  const source = fixtures["/api/notices/6"] as Record<string, unknown>;
  await page.route("**/api/notices/6", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      // 같은 값이어도 합치지 않는지, 개찰 키가 있으면 일시를 읽는지 함께 본다.
      body: JSON.stringify({
        ...source,
        budget: source.estimated_price,
        lifecycle: { ...(source.lifecycle as Record<string, unknown>), opening_at: "2026-10-02T06:00:00+09:00" },
      }),
    });
  });
  await page.goto(`/judgments/6?run=${encodeURIComponent(RUN_ID)}`);
  await expect(page.locator(".notice-record-facts")).toBeVisible({ timeout: 10_000 });

  const facts = await noticeFacts(page);
  expect(facts["예산 (원문 제공 금액)"]).toBe("409,090,909원");
  expect(facts["추정가격"]).toBe("409,090,909원");
  expect(facts["개찰"]).toContain("2026");
  expect(facts["개찰"]).not.toBe("미제공");

  const performance = page.locator(".performance-matches-panel");
  await expect(performance.locator(".panel-note")).toHaveText("최고 유사도 0.67");
  await expect(performance).toContainText("유사도는 수집 단계의 모델 점수이며 판단 보조예요.");
  await expect(performance.getByText("대조된 실적 없음")).toHaveCount(0);

  const retrieved = performance.locator(".performance-matches-block").filter({ hasText: "수집 탐색 신호" }).locator("tbody tr");
  await expect(retrieved).toHaveCount(1);
  await expect(retrieved.first()).toContainText("가상 블록체인 서비스 실증 사례 O");
  // 유사도는 소수 2자리 모델 점수다.
  await expect(retrieved.first().locator("td").nth(1)).toHaveText("0.67");
  await expect(retrieved.first()).toContainText("42쪽");
  // `legal_qualification_status`는 확인 자료가 없어 항상 unknown이고 `미확인`으로 읽는다.
  await expect(retrieved.first().locator("td").nth(4)).toHaveText("미확인");

  const judged = performance.locator(".performance-matches-block").filter({ hasText: "판정 검토 결과" }).locator("tbody tr");
  await expect(judged).toHaveCount(1);
  // 유사도가 설명하지 못하는 차이를 숨기지 않는다.
  await expect(judged.first()).toContainText("요구 기능이 다르며");
  await expect(judged.first().locator("td").nth(4)).toHaveText("미확인");
});
