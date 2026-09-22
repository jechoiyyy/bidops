import { expect, test, type Page } from "@playwright/test";
import { mockApi } from "./api-mock";
import {
  BINDABLE_EVALUATION,
  COMPARISON_EVALUATION,
  LONG_SECTION_TITLE,
  MISMATCHED_EVALUATION,
  POLICY_ACTIVE,
  POLICY_CANDIDATE,
  POLICY_DRAFT,
  mockCriteria,
  type CriteriaMockCalls,
  type CriteriaMockOptions,
} from "./criteria-fixtures";

/**
 * 판정 기준 화면 — 회사 프로필 · 판정 정책 · 품질 게이트 · 검증 지표.
 *
 * 승인된 시안(`design-previews/bidops-criteria-runstatus-erp-20260907/`)의 구현이다.
 * 이 spec은 화면이 **업무 상태를 옳게 말하는가**를 본다: 조회 실패를 0으로 접지
 * 않는지, 모델 비교 결과를 운영 활성화 근거로 쓰지 않는지, 확인 창이 대상과 근거를
 * 고정하는지, 충돌이 담당자의 입력을 지우지 않는지, 회차별 조회 범위를 밝히는지.
 *
 * 공유 `api-mock.ts`는 고치지 않는다. 고정 입력은 `criteria-fixtures.ts`가 주며
 * 모든 mutation은 가로챈 mock으로만 나간다.
 */

async function open(page: Page, path: string, options: CriteriaMockOptions = {}): Promise<CriteriaMockCalls> {
  await mockApi(page);
  const calls = await mockCriteria(page, options);
  await page.goto(path);
  return calls;
}

const workspace = (page: Page) => page.locator(".crit-workspace");
const summary = (page: Page) => page.locator(".crit-summary");
const detailFooter = (page: Page) => page.locator(".crit-detail-foot");
const UI_SCALE = 0.9;
const physical = (logical: number) => logical * UI_SCALE;

// ── 화면 골격과 탭 ────────────────────────────────────────────────────

test("네 탭이 각자의 정식 주소로 열리고 목록 38% · 상세 62%를 유지한다", async ({ page }) => {
  for (const [path, tab] of [["/profile", "회사 프로필"], ["/policies", "판정 정책"], ["/quality-gates", "품질 게이트"], ["/metrics", "검증 지표"]] as const) {
    await open(page, path);
    await expect(page.getByRole("tab", { name: tab, exact: true })).toHaveAttribute("aria-selected", "true");
    await expect(workspace(page)).toBeVisible();
    const ratio = await workspace(page).evaluate((node) => {
      const queue = node.querySelector(".crit-queue") as HTMLElement | null;
      return queue ? queue.getBoundingClientRect().width / node.getBoundingClientRect().width : 0;
    });
    expect(ratio).toBeGreaterThan(0.36);
    expect(ratio).toBeLessThan(0.4);
  }
});

test("보이지 않는 탭의 조회는 함께 나가지 않는다", async ({ page }) => {
  const requested: string[] = [];
  page.on("request", (request) => {
    const path = new URL(request.url()).pathname;
    if (path.startsWith("/api/")) requested.push(path);
  });
  await open(page, "/profile");
  await expect(workspace(page)).toBeVisible();
  await expect(page.getByText("사업·기술 역량").first()).toBeVisible();
  // `확인 요청 · 프로필 절 기준` 절은 이 탭에서만 회차 목록·통계를 조회한다
  // (H3, ADR-0066 결정 7·2). 조회가 끝날 때까지 기다린 뒤 요청 목록을 본다.
  await expect(page.locator(".crit-verification-requests")).toContainText("run-0906-a");

  // 요약 줄이 쓰는 둘과 확인 요청 절이 쓰는 회차 조회만 이 탭에서 나간다. 다른
  // 탭 전용의 무거운 조회는 나가지 않는다.
  expect(requested).toContain("/api/profile/sections");
  expect(requested).toContain("/api/policies");
  expect(requested).toContain("/api/runs");
  expect(requested.filter((path) => path.startsWith("/api/quality-gates"))).toHaveLength(0);
  expect(requested.filter((path) => path.startsWith("/api/metrics"))).toHaveLength(0);
});

test("경계 안내는 이 화면이 정하지 않는 네 판단을 모든 탭에 남긴다", async ({ page }) => {
  for (const path of ["/criteria", "/profile", "/policies", "/quality-gates", "/metrics"]) {
    await open(page, path);
    const boundary = page.locator(".crit-boundary");
    await expect(boundary).toContainText("적합성 등급");
    await expect(boundary).toContainText("참여 준비");
    await expect(boundary).toContainText("추적 선택");
    await expect(boundary).toContainText("Go/No-Go");
    await expect(boundary).toContainText("소급해 바꾸지 않습니다");
    await expect(boundary).toContainText("이후 실행에만 적용");
  }
});

test("탭을 옮겨도 회차와 다른 화면의 선택이 지워지지 않는다", async ({ page }) => {
  await open(page, "/profile?run=run-0905-a&notice=notice-9");
  await page.getByRole("tab", { name: "판정 정책", exact: true }).click();
  await expect.poll(() => new URL(page.url()).pathname).toBe("/policies");
  const params = new URL(page.url()).searchParams;
  expect(params.get("run")).toBe("run-0905-a");
  expect(params.get("notice")).toBe("notice-9");
});

// ── 요약 한 줄 ────────────────────────────────────────────────────────

test("요약은 실제 프로필 버전·운영 활성 정책·미확인 수를 말한다", async ({ page }) => {
  await open(page, "/profile");
  await expect(summary(page)).toContainText("company-profile.sha256:");
  await expect(summary(page)).toContainText("읽기 전용");
  await expect(summary(page)).toContainText(POLICY_ACTIVE);
  await expect(summary(page).getByRole("button", { name: "미확인 항목 4" })).toBeVisible();
});

test("정책 조회 실패는 운영 활성 없음이 아니라 미확인이다", async ({ page }) => {
  await mockApi(page);
  await mockCriteria(page);
  await page.route("**/api/policies", async (route) => {
    if (route.request().method() === "GET") await route.fulfill({ status: 500, contentType: "application/json", body: "{}" });
    else await route.fallback();
  });
  await page.goto("/profile");
  await expect(summary(page)).toContainText("미확인");
  await expect(summary(page)).not.toContainText("운영 활성 없음");
  await expect(summary(page)).toContainText("활성 정책 없음을 뜻하지 않습니다");
});

test("요약의 미확인 항목은 회사 프로필 탭의 미확인 필터를 켠다", async ({ page }) => {
  await open(page, "/metrics?run=run-0905-a");
  await summary(page).getByRole("button", { name: /미확인 항목/ }).click();
  await expect.poll(() => new URL(page.url()).pathname).toBe("/profile");
  expect(new URL(page.url()).searchParams.get("pstatus")).toBe("unknown");
  expect(new URL(page.url()).searchParams.get("run")).toBe("run-0905-a");
  await expect(page.getByRole("group", { name: "확인 상태 필터" }).getByRole("button", { name: "미확인" })).toHaveAttribute("aria-pressed", "true");
});

// ── 회사 프로필 ───────────────────────────────────────────────────────

test("프로필은 계층 절과 값 없음·빈 목록·빈 문자열을 구분해 보여 준다", async ({ page }) => {
  await open(page, "/profile?psection=capability");
  const detail = page.locator(".crit-detail-scroll");
  await expect(detail).toContainText("데이터 수집·연계, 분석 서비스 구축");
  // unknown 항목의 값은 null이다. 빈 문자열·빈 목록과 다른 문구를 쓴다.
  await expect(detail).toContainText("값 미기록");
  await expect(detail).toContainText("값 없음 (빈 목록)");
  // 하위 절이 계층 그대로 붙는다.
  await expect(detail.locator(".crit-tree-child")).toContainText("보유 도구");
  await expect(detail).toContainText("추가 확인 필요");
});

test("구조화하지 못한 절은 그 사실을 그대로 알린다", async ({ page }) => {
  await open(page, "/profile?psection=certification");
  const alert = page.locator(".crit-detail-scroll [role='alert']").first();
  await expect(alert).toContainText("이 절의 일부 내용을 구조화하지 못했습니다");
  await expect(alert).toContainText("profile_section_unstructured");
});

test("프로필의 불완전한 응답은 상태와 미확인을 0으로 확정하지 않는다", async ({ page }) => {
  await open(page, "/profile", { profile: "invalid" });
  await expect(page.locator(".crit-pane-foot")).toContainText("확정 미확인");
  await expect(page.locator(".crit-pane-foot")).toContainText("추정 미확인");
  await expect(page.locator(".crit-pane-foot")).toContainText("미확인 미확인");
  await expect(page.locator(".crit-pane-foot")).not.toContainText("확정 0");
  // 절 트리가 파싱 실패를 말하면 미확인 "0건"은 아는 0이 아니다.
  await expect(summary(page).getByRole("button", { name: "미확인 항목 · 확인 불가" })).toBeVisible();
  await expect(summary(page)).not.toContainText(/미확인 항목 0(?:\D|$)/);
  await expect(page.locator(".crit-detail").getByRole("alert")).toContainText("프로필 응답 확인 필요");
  await expect(page.locator(".crit-pane-head")).toContainText("건수 미확인");
  await expect(page.locator(".crit-detail")).not.toContainText("승인된 사본에 표시할 절이 없습니다");
  await expect(page.locator(".crit-detail").getByRole("button", { name: "다시 조회" })).toBeVisible();
});

test("프로필 읽기 실패는 빈 정상 상태가 아니라 오류 상태로 표시한다", async ({ page }) => {
  await open(page, "/profile", { profile: "read-error" });
  await expect(page.getByRole("alert")).toContainText("회사 프로필을 불러오지 못했습니다.");
  await expect(page.getByRole("alert")).toContainText("0건이나 정상 상태로 표시하지 않습니다");
});

test("검색과 상태 필터는 실제 필드에 작동하고 주소에 남는다", async ({ page }) => {
  await open(page, "/profile");
  await page.getByRole("textbox", { name: "프로필 항목 검색" }).fill("블록체인");
  await expect.poll(() => new URL(page.url()).searchParams.get("pq")).toBe("블록체인");
  await expect(page.locator(".crit-queue-scroll .crit-record")).toHaveCount(1);
  await expect(page.locator(".crit-queue-scroll")).toContainText("사업·기술 역량");

  await page.getByRole("textbox", { name: "프로필 항목 검색" }).fill("존재하지 않는 항목");
  await expect(page.locator(".crit-queue-scroll")).toContainText("검색·필터 조건에 맞는 절이 없습니다");
  await expect(page.locator(".crit-detail")).toContainText("조건에 맞는 절이 없습니다");
});

test("미확인 필터는 미확인 항목이 있는 절만 남긴다", async ({ page }) => {
  await open(page, "/profile?pstatus=unknown");
  const records = page.locator(".crit-queue-scroll .crit-record");
  await expect(records).toHaveCount(3);
  await expect(page.locator(".crit-queue-scroll")).not.toContainText("기본 정보");
});

test("사본 정보 창은 버전·해시·읽기 전용을 보여 주고 편집 진입점을 두지 않는다", async ({ page }) => {
  await open(page, "/profile");
  await detailFooter(page).getByRole("button", { name: "사본 정보" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toContainText("company-profile.sha256:");
  await expect(dialog).toContainText("승인된 구조화 항목 · 읽기 전용");
  await expect(dialog).toContainText("프로필 편집 API가 없습니다");
  await expect(page.getByRole("button", { name: /프로필 (편집|업로드)/ })).toHaveCount(0);
});

test("판정 참조 횟수는 집계 불가와 실제 0회를 구분한다", async ({ page }) => {
  await open(page, "/profile?psection=certification");
  await page.getByRole("group").getByText("기술 키와 판정 참조 횟수", { exact: false }).click();
  const detail = page.locator(".crit-detail-scroll");
  await expect(detail).toContainText("집계 불가 · 판정 원문을 읽지 못했습니다");
  await expect(detail).toContainText("2회");
});

// ── 확인 요청 · 프로필 절 기준(H3, ADR-0066 결정 7·2) ──────────────────

test("확인 요청 · 프로필 절 기준 절은 프로필 절이 식별된 항목만 보이고 회차 기준을 밝힌다", async ({ page }) => {
  await open(page, "/profile");
  const panel = page.locator(".crit-verification-requests");
  await expect(panel).toContainText("실적 증빙 확인");
  await expect(panel).toContainText("2.1 보유 도구");
  await expect(panel).toContainText("자격 서류 확인");
  await expect(panel).toContainText("3 실적");
  // 프로필 절이 식별되지 않은 항목(공고별로만 걸리는 것)은 이 절에 없다 —
  // 대시보드 `사람 확인 필요` 패널이 맡는다.
  await expect(panel).not.toContainText("공고별 확인 항목");
  await expect(panel).toContainText("run-0906-a");
});

test("확인 요청 절의 회차 선택은 run 파라미터를 바꾼다", async ({ page }) => {
  await open(page, "/profile");
  const panel = page.locator(".crit-verification-requests");
  await panel.getByRole("button", { name: "회차 선택" }).click();
  await page.getByRole("dialog").getByLabel("대상 회차").click();
  await page.getByRole("option", { name: /run-0904-a/ }).click();
  await expect.poll(() => new URL(page.url()).searchParams.get("run")).toBe("run-0904-a");
});

// ── 판정 정책 ─────────────────────────────────────────────────────────

test("활성화 후보 목록에는 최신 통과 운영 평가만 오른다", async ({ page }) => {
  await open(page, `/policies?policy=${encodeURIComponent(POLICY_CANDIDATE)}&ptab=approval`);
  await page.getByLabel("통과한 최신 운영 evaluation").click();
  const options = page.getByRole("option");
  await expect(options).toHaveCount(1);
  await expect(options.first()).toContainText(BINDABLE_EVALUATION);
  // 모델 비교와 프롬프트 불일치는 수치가 통과여도 근거가 될 수 없다.
  await expect(page.getByRole("listbox")).not.toContainText(COMPARISON_EVALUATION);
  await expect(page.getByRole("listbox")).not.toContainText(MISMATCHED_EVALUATION);
});

test("정책 활성화는 담당자 없이 나가지 않고 결합 입력을 고정해 보여 준다", async ({ page }) => {
  const calls = await open(page, `/policies?policy=${encodeURIComponent(POLICY_CANDIDATE)}&ptab=approval`);
  const activate = detailFooter(page).getByRole("button", { name: "정책 활성화 확인" });
  await expect(activate).toBeDisabled();

  await page.getByLabel("통과한 최신 운영 evaluation").click();
  await page.getByRole("option", { name: new RegExp(BINDABLE_EVALUATION) }).click();
  await expect(activate).toBeEnabled();
  await activate.click();

  const dialog = page.getByRole("dialog");
  await expect(dialog).toContainText(POLICY_CANDIDATE);
  await expect(dialog).toContainText(BINDABLE_EVALUATION);
  await expect(dialog).toContainText("합성-모델:27b");
  await expect(dialog).toContainText("company-profile.sha256:");
  const confirm = dialog.getByRole("button", { name: "정책 활성화" });
  await expect(confirm).toBeDisabled();

  await dialog.getByLabel("활성화 담당자 · 필수").fill("합성 승인자");
  await expect(confirm).toBeEnabled();
  await confirm.click();

  await expect.poll(() => calls.policyActivate.length).toBe(1);
  expect(calls.policyActivate[0].policyVersion).toBe(POLICY_CANDIDATE);
  expect(calls.policyActivate[0].body).toEqual({ quality_gate_result_id: BINDABLE_EVALUATION, confirmed_by: "합성 승인자" });
  await expect(page.locator(".crit-detail-scroll")).toContainText("정책이 활성화되었습니다");
});

test("활성화 충돌은 창을 닫지 않고 담당자 입력을 남긴다", async ({ page }) => {
  const calls = await open(page, `/policies?policy=${encodeURIComponent(POLICY_CANDIDATE)}&ptab=approval`, { policyMutationStatus: 409 });
  await page.getByLabel("통과한 최신 운영 evaluation").click();
  await page.getByRole("option", { name: new RegExp(BINDABLE_EVALUATION) }).click();
  await detailFooter(page).getByRole("button", { name: "정책 활성화 확인" }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("활성화 담당자 · 필수").fill("합성 승인자");
  await dialog.getByRole("button", { name: "정책 활성화" }).click();

  await expect(dialog.getByRole("alert")).toContainText("입력은 그대로 두었습니다");
  await expect(dialog).toBeVisible();
  await expect(dialog.getByLabel("활성화 담당자 · 필수")).toHaveValue("합성 승인자");
  expect(calls.policyActivate).toHaveLength(1);
});

test("후보 지정과 활성화는 서로 다른 조작이다", async ({ page }) => {
  const calls = await open(page, `/policies?policy=${encodeURIComponent(POLICY_DRAFT)}`);
  await expect(detailFooter(page).getByRole("button", { name: "정책 활성화 확인" })).toHaveCount(0);
  await detailFooter(page).getByRole("button", { name: "활성화 후보 지정" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toContainText("draft → activation_candidate");
  await expect(dialog).toContainText("후보 지정은 운영 활성화가 아닙니다");
  await dialog.getByLabel("확인 담당자 · 필수").fill("합성 담당자");
  await dialog.getByRole("button", { name: "후보로 지정" }).click();
  await expect.poll(() => calls.policyCandidate.length).toBe(1);
  expect(calls.policyCandidate[0].body).toEqual({ confirmed_by: "합성 담당자" });
  expect(calls.policyActivate).toHaveLength(0);
});

test("새 정책 버전 폼은 다섯 JSON 본문을 그대로 보낸다", async ({ page }) => {
  const calls = await open(page, "/policies");
  await page.locator(".crit-queue-tools").getByRole("button", { name: "새 정책 버전" }).click();
  const dialog = page.getByRole("dialog");
  for (const label of ["관점별 검토 프롬프트 · 필수", "반론 프롬프트 · 필수", "종합 프롬프트 · 필수", "후보 선정 · 필수", "임계값 · 필수"]) {
    await expect(dialog.getByLabel(label)).toBeVisible();
  }
  await dialog.getByLabel("정책 버전 · 필수").fill("screening-policy.v4.20260907");
  await dialog.getByLabel("프롬프트 버전 · 필수").fill("screening-prompt.v4");
  await dialog.getByLabel("임계값 · 필수").fill("{ \"grade_cutoff\": 0.7 }");
  await dialog.getByLabel("생성 담당자 · 필수").fill("합성 담당자");
  await dialog.getByRole("button", { name: "새 불변 버전 저장" }).click();

  await expect.poll(() => calls.policyCreate.length).toBe(1);
  expect(calls.policyCreate[0]).toEqual({
    policy_version: "screening-policy.v4.20260907",
    prompt_version: "screening-prompt.v4",
    created_by: "합성 담당자",
    perspective_prompts: {},
    counterargument_prompt: {},
    synthesis_prompt: {},
    candidate_selection: {},
    thresholds: { grade_cutoff: 0.7 },
  });
});

test("정책 본문의 JSON 문법 오류는 저장하지 않는다", async ({ page }) => {
  const calls = await open(page, "/policies");
  await page.locator(".crit-queue-tools").getByRole("button", { name: "새 정책 버전" }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("정책 버전 · 필수").fill("screening-policy.v5");
  await dialog.getByLabel("프롬프트 버전 · 필수").fill("screening-prompt.v5");
  await dialog.getByLabel("생성 담당자 · 필수").fill("합성 담당자");
  await dialog.getByLabel("후보 선정 · 필수").fill("[1, 2]");
  await dialog.getByRole("button", { name: "새 불변 버전 저장" }).click();
  await expect(dialog.getByRole("alert")).toContainText("JSON object여야 합니다");
  expect(calls.policyCreate).toHaveLength(0);
});

test("정책 내용은 본문 키를 그대로 보여 주고 업무 의미로 바꾸지 않는다", async ({ page }) => {
  await open(page, `/policies?policy=${encodeURIComponent(POLICY_CANDIDATE)}`);
  const detail = page.locator(".crit-detail-scroll");
  await expect(detail).toContainText("perspective_prompts");
  await expect(detail).toContainText("technical_fit, experience_fit");
  await expect(detail).toContainText("화면은 정책 본문의 키를 업무 의미로 해석하지 않습니다");
});

// ── 품질 게이트 ───────────────────────────────────────────────────────

test("모델 비교 게이트는 운영 활성화에 쓸 수 없다고 목록과 상세가 함께 말한다", async ({ page }) => {
  await open(page, "/quality-gates?gate=gate-model-comparison");
  await expect(page.locator(".crit-queue-scroll")).toContainText("운영 활성화에 사용 불가");
  await expect(page.locator(".crit-detail-scroll").getByRole("alert")).toContainText("모델 비교 결과는 운영 활성화에 사용할 수 없습니다");
  await expect(detailFooter(page)).toContainText("운영 활성화에 연결 불가");
});

test("평가 수치 누락은 0/10이 아니라 계산 불가로 남는다", async ({ page }) => {
  await open(page, "/quality-gates?gate=gate-model-comparison&gtab=reviews");
  const stats = page.locator(".crit-stat-line");
  await expect(stats).toContainText("계산 불가 / 10건");
  await expect(stats).not.toContainText("0 / 10건");
});

test("보류는 미달이 아니며 리뷰 수로 통과를 만들지 않는다", async ({ page }) => {
  await open(page, "/quality-gates?gate=gate-operational-held");
  await expect(page.locator(".crit-detail-head")).toContainText("보류");
  await expect(page.locator(".crit-detail-scroll")).toContainText("계산 보류는 미달이 아닙니다");
  await page.getByRole("tab", { name: "담당자 리뷰" }).click();
  await expect(page.locator(".crit-detail-scroll")).toContainText("리뷰 개수가 채워졌다는 이유만으로 화면이 통과 판정을 만들지 않습니다");
});

test("게이트 상세 조회 실패는 게이트 없음으로 접히지 않는다", async ({ page }) => {
  await open(page, "/quality-gates?gate=gate-operational-pass", { gateDetailError: "gate-operational-pass" });
  const alert = page.locator(".crit-detail").getByRole("alert");
  await expect(alert).toContainText("선택한 게이트의 상세를 불러오지 못했습니다");
  await expect(alert).toContainText("선택한 게이트가 없어진 것이 아니라");
  // 목록은 그대로 남는다.
  await expect(page.locator(".crit-queue-scroll .crit-record")).toHaveCount(4);
});

test("고정 입력과 계산 이력은 수정본을 덮지 않고 모두 남긴다", async ({ page }) => {
  await open(page, "/quality-gates?gate=gate-operational-pass&gtab=binding");
  const detail = page.locator(".crit-detail-scroll");
  await expect(detail).toContainText("합성-모델:27b");
  await expect(detail).toContainText("run-0904-a");
  await expect(detail).toContainText("gate-operational-pass-a");
  await expect(detail).toContainText("계산 이력 · 수정본 3건");
  await expect(detail).toContainText("3 · 최신");
  await expect(detail).toContainText("이전 수정본을 덮지 않습니다");
});

test("근거 리뷰 저장은 계약 payload로 나가고 충돌은 입력을 남긴다", async ({ page }) => {
  const calls = await open(page, "/quality-gates?gate=gate-operational-pass", { policyMutationStatus: 409 });
  await detailFooter(page).getByRole("button", { name: "근거 리뷰 작성" }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("Pass A 공고 ID · 필수").fill("notice-109");
  await dialog.getByLabel("리뷰 담당자 · 필수").fill("합성 검토자");
  await dialog.getByRole("button", { name: "근거 리뷰 저장" }).click();

  await expect.poll(() => calls.reviewUpsert.length).toBe(1);
  expect(calls.reviewUpsert[0]).toEqual({
    gateId: "gate-operational-pass",
    noticeId: "notice-109",
    body: { reviewer: "합성 검토자", evidence_judgment: "동의", note: null },
  });
  await expect(dialog.getByRole("alert")).toContainText("입력은 그대로 두었습니다");
  await expect(dialog.getByLabel("Pass A 공고 ID · 필수")).toHaveValue("notice-109");
});

test("새 품질 게이트 창은 목적에 맞는 프로필 출처를 고정하고 계약대로 보낸다", async ({ page }) => {
  const calls = await open(page, "/quality-gates");
  await page.locator(".crit-queue-tools").getByRole("button", { name: "새 품질 게이트" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toContainText("current");

  await dialog.getByLabel("검증 목적 · 필수").click();
  await page.getByRole("option", { name: /모델 비교/ }).click();
  await expect(dialog).toContainText("git:ee621835db934ddac944f7a07a986ed0b73ecc7a");
  await expect(dialog.getByRole("note")).toContainText("운영 활성화에 사용할 수 없습니다");

  await dialog.getByLabel("검증 목적 · 필수").click();
  await page.getByRole("option", { name: /운영 승인/ }).click();
  await dialog.getByLabel("정책 버전 · 필수").click();
  await page.getByRole("option", { name: new RegExp(POLICY_CANDIDATE) }).click();
  await dialog.getByLabel("생성 담당자 · 필수").fill("합성 담당자");
  await dialog.getByRole("button", { name: "게이트 생성" }).click();

  await expect.poll(() => calls.gateCreate.length).toBe(1);
  expect(calls.gateCreate[0]).toEqual({
    purpose: "operational_approval",
    policy_version: POLICY_CANDIDATE,
    profile_source: "current",
    created_by: "합성 담당자",
  });
});

test("지표 표는 모든 top-level 지표와 제외 근거를 함께 남긴다", async ({ page }) => {
  await open(page, "/quality-gates?gate=gate-operational-pass");
  const detail = page.locator(".crit-detail-scroll");
  await expect(detail).toContainText("grade_reproducibility");
  await expect(detail).toContainText("evidence_validity.agreement");
  await expect(detail).toContainText("claude_alignment");
  await expect(detail).toContainText("notice-033");
  await expect(detail).toContainText("합성 제외 사유");
  // 계산하지 않은 지표는 0%가 아니라 계산 불가로 남는다.
  await expect(detail).toContainText("계산 불가");
});

// ── 검증 지표 ─────────────────────────────────────────────────────────

test("회차별 추이는 최근 회차만 조회하고 그 범위를 밝힌다", async ({ page }) => {
  const requested: string[] = [];
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (url.pathname === "/api/metrics/validation") requested.push(url.searchParams.get("run_id") ?? "");
  });
  await open(page, "/metrics");
  await expect(page.locator(".crit-detail-scroll")).toContainText("최근 5개 회차");
  await expect(page.locator(".crit-detail-scroll")).toContainText("전체 회차 7개");
  await expect(page.locator(".crit-detail-scroll")).toContainText("조회 범위 밖 회차의 값은 미확인이며 없음을 뜻하지 않습니다");
  await expect.poll(() => new Set(requested).size).toBe(5);
});

test("과거 회차 하나가 실패해도 나머지 회차의 값은 남는다", async ({ page }) => {
  await open(page, "/metrics", { metricsFailures: ["run-0903-a"] });
  const detail = page.locator(".crit-detail-scroll");
  await expect(detail.getByRole("alert")).toContainText("과거 회차 지표 1건을 불러오지 못했습니다");
  await expect(detail).toContainText("조회 실패");
  await expect(detail).toContainText("98.3%");
  await expect(detail).toContainText("96.7%");
});

test("계산 불가와 값 미확인을 0%로 바꾸지 않는다", async ({ page }) => {
  await open(page, "/metrics?metric=human_agreement_rate");
  const detail = page.locator(".crit-detail-scroll");
  await expect(detail).toContainText("계산 불가");
  await expect(detail).toContainText("0%로 표시하지 않습니다");
  await expect(detail).toContainText("담당자 리뷰가 기준 수에 미치지 못해");
  await expect(page.locator(".crit-stat-line")).not.toContainText("0.0%");
});

test("실제 0과 계산 불가는 다른 지표에서 다르게 적힌다", async ({ page }) => {
  await open(page, "/metrics?metric=grade_readiness_mixing_rate");
  await expect(page.locator(".crit-stat-line")).toContainText("0.0%");
  await expect(page.locator(".crit-detail-scroll")).toContainText("사전 확정 임계값 없음");
});

test("회차 선택기는 run 파라미터만 바꾸고 다른 쿼리를 지우지 않는다", async ({ page }) => {
  await open(page, "/metrics?run=run-0906-a&notice=notice-9");
  await detailFooter(page).getByRole("button", { name: "회차 선택" }).click();
  await page.getByRole("dialog").getByLabel("대상 회차").click();
  await page.getByRole("option", { name: /run-0904-a/ }).click();
  await expect.poll(() => new URL(page.url()).searchParams.get("run")).toBe("run-0904-a");
  expect(new URL(page.url()).searchParams.get("notice")).toBe("notice-9");
  await expect(page.locator(".crit-detail-head")).toContainText("2026-09-02 ~ 2026-09-04");
});

test("지표 목록은 서버가 준 key·label·상태를 그대로 쓴다", async ({ page }) => {
  await open(page, "/metrics");
  const queue = page.locator(".crit-queue-scroll");
  await expect(queue).toContainText("근거 연결률");
  await expect(queue).toContainText("감사 표본 누락률");
  await expect(queue).toContainText("기준 · 95% 이상");
  await expect(queue).toContainText("기준 · 사전 확정 임계값 없음");
  await expect(page.locator(".crit-detail-head")).toContainText("evidence_link_rate");
});

// ── 폭·긴 제목 ────────────────────────────────────────────────────────

/**
 * 승인 시안을 실제로 렌더해 잰 값이다(부모가 잰 `reference-geometry.json`).
 * 요약 줄 49 = 내용 32 + 위아래 패딩 16 + 테두리 1, 하단 액션 57 = 32 + 24 + 1,
 * 탭 37(Astryx 밑줄), 요약 줄과 작업 영역 사이 이음매 0, 하단 단추 본문 14px.
 */
for (const width of [1280, 1440]) {
  test(`시안 실측 치수를 ${width}px에서 유지한다`, async ({ page }) => {
    await page.setViewportSize({ width, height: width === 1280 ? 800 : 900 });
    await open(page, "/policies");
    await expect(page.locator(".crit-record-title").first()).toBeVisible();
    const geometry = await page.evaluate(() => {
      const box = (selector: string) => document.querySelector(selector)?.getBoundingClientRect() ?? null;
      const strip = box(".crit-summary");
      const work = box(".crit-workspace");
      const button = document.querySelector(".crit-detail-foot .astryx-button");
      const boundaryNode = document.querySelector(".crit-boundary") as HTMLElement | null;
      const boundaryStyle = boundaryNode ? window.getComputedStyle(boundaryNode) : null;
      return {
        tabs: Math.round(box(".crit-tabs .astryx-tab-list")?.height ?? 0),
        strip: Math.round(strip?.height ?? 0),
        footer: Math.round(box(".crit-detail-foot")?.height ?? 0),
        seam: Math.round((work?.top ?? 0) - (strip?.bottom ?? 0)),
        workspaceBottom: Math.round(work?.bottom ?? 0),
        boundaryFont: boundaryStyle?.fontSize ?? "",
        // 한 줄인가. 문단 높이를 줄 높이로 나눠 본다.
        boundaryLines: boundaryNode && boundaryStyle
          ? Math.round((boundaryNode.clientHeight - parseFloat(boundaryStyle.paddingTop) - parseFloat(boundaryStyle.paddingBottom)) / parseFloat(boundaryStyle.lineHeight))
          : 0,
        buttonFont: button ? window.getComputedStyle(button).fontSize : "",
        listTitleFont: window.getComputedStyle(document.querySelector(".crit-record-title") as Element).fontSize,
        listTitleWeight: window.getComputedStyle(document.querySelector(".crit-record-title") as Element).fontWeight,
        detailTitleFont: window.getComputedStyle(document.querySelector(".crit-detail-head h2") as Element).fontSize,
      };
    });
    expect(geometry.seam).toBe(0);
    expect(geometry.strip).toBeCloseTo(physical(49), 0);
    expect(geometry.footer).toBeCloseTo(physical(57), 0);
    expect(geometry.tabs).toBeCloseTo(physical(37), 0);
    expect(geometry.buttonFont).toBe("12.6px");
    expect(geometry.listTitleFont).toBe("13.5px");
    expect(geometry.listTitleWeight).toBe("600");
    expect(geometry.detailTitleFont).toBe("18px");
    // 각주는 두 폭 모두 한 줄이다. 두 줄이 되면 작업 영역이 그만큼 짧아진다.
    expect(geometry.boundaryLines).toBe(1);
    expect(geometry.boundaryFont).toBe("10.8px");
    // The native compact shell fills the viewport while preserving the former
    // 90%-rendered bottom inset.
    const viewportHeight = width === 1280 ? 800 : 900;
    expect(geometry.workspaceBottom).toBeCloseTo(viewportHeight - physical(37), 0);
  });

  test(`하단 액션이 ${width}px에서 스크롤 없이 보이고 화면이 가로로 넘치지 않는다`, async ({ page }) => {
    await page.setViewportSize({ width, height: width === 1280 ? 800 : 900 });
    await open(page, "/policies");
    const footer = detailFooter(page);
    await expect(footer).toBeInViewport();
    const overflow = await page.evaluate(() => ({
      document: document.documentElement.scrollWidth - document.documentElement.clientWidth,
      body: document.body.scrollWidth - document.body.clientWidth,
    }));
    expect(overflow.document).toBeLessThanOrEqual(1);
    expect(overflow.body).toBeLessThanOrEqual(1);
  });
}

test("확인 창의 액션은 1280px에서도 화면 안에 남는다", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 });
  await open(page, `/policies?policy=${encodeURIComponent(POLICY_CANDIDATE)}&ptab=approval`);
  await page.getByLabel("통과한 최신 운영 evaluation").click();
  await page.getByRole("option", { name: new RegExp(BINDABLE_EVALUATION) }).click();
  await detailFooter(page).getByRole("button", { name: "정책 활성화 확인" }).click();
  const dialog = page.getByRole("dialog");
  // 되돌릴 수 없는 조작의 확인 단추가 화면 밖으로 밀리면 안 된다.
  await expect(dialog.getByRole("button", { name: "정책 활성화" })).toBeInViewport();
  await expect(dialog.getByLabel("활성화 담당자 · 필수")).toBeInViewport();
});

test("확인 창은 응답이 오기 전까지 취소·Esc로 닫히지 않는다", async ({ page }) => {
  // 응답을 붙잡아 둔 상태에서만 "요청 중"을 실제로 볼 수 있다.
  const calls = await open(page, `/policies?policy=${encodeURIComponent(POLICY_DRAFT)}`, { deferPolicyMutation: true });
  await detailFooter(page).getByRole("button", { name: "활성화 후보 지정" }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("확인 담당자 · 필수").fill("합성 담당자");
  await dialog.getByRole("button", { name: "후보로 지정" }).click();

  await expect(dialog.getByRole("button", { name: "요청 중…" })).toBeDisabled();
  await expect(dialog.getByRole("button", { name: "취소" })).toBeDisabled();
  await dialog.getByRole("button", { name: "취소" }).click({ force: true });
  await expect(dialog).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(dialog).toBeVisible();
  // 중복 제출도 막는다.
  expect(calls.policyCandidate).toHaveLength(1);

  calls.releasePolicyMutation();
  await expect(dialog).toBeHidden();
  expect(calls.policyCandidate).toHaveLength(1);
});

test("대상이 다른 확인 창은 담당자 이름을 물려받지 않는다", async ({ page }) => {
  await open(page, `/policies?policy=${encodeURIComponent(POLICY_DRAFT)}`);
  await detailFooter(page).getByRole("button", { name: "활성화 후보 지정" }).click();
  let dialog = page.getByRole("dialog");
  await dialog.getByLabel("확인 담당자 · 필수").fill("첫 담당자");
  await dialog.getByRole("button", { name: "취소" }).click();
  await expect(dialog).toBeHidden();

  // 다른 대상의 확인 창에 앞 담당자 이름이 남으면 감사 기록이 틀린다.
  await open(page, `/policies?policy=${encodeURIComponent(POLICY_CANDIDATE)}&ptab=approval`);
  await page.getByLabel("통과한 최신 운영 evaluation").click();
  await page.getByRole("option", { name: new RegExp(BINDABLE_EVALUATION) }).click();
  await detailFooter(page).getByRole("button", { name: "정책 활성화 확인" }).click();
  dialog = page.getByRole("dialog");
  await expect(dialog.getByLabel("활성화 담당자 · 필수")).toHaveValue("");
});

/**
 * 문서를 다시 읽는 `page.goto`는 화면 상태를 통째로 버리므로 이 회귀를 증명하지
 * 못한다. SPA 안에서 주소만 바뀌는 상황(뒤로 가기·목록 선택)을 흉내 내야 한다.
 */
async function changeSelectionInPage(page: Page, search: string): Promise<void> {
  await page.evaluate((next) => {
    window.history.pushState({}, "", next);
    window.dispatchEvent(new PopStateEvent("popstate"));
  }, search);
}

test("근거 리뷰 창은 열린 순간의 게이트에만 저장한다", async ({ page }) => {
  const calls = await open(page, "/quality-gates?gate=gate-operational-pass");
  await detailFooter(page).getByRole("button", { name: "근거 리뷰 작성" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toContainText("저장 대상 게이트 · gate-operational-pass");
  await dialog.getByLabel("Pass A 공고 ID · 필수").fill("notice-109");
  await dialog.getByLabel("리뷰 담당자 · 필수").fill("합성 검토자");

  // 창이 열린 채로 SPA 안에서 선택이 다른 게이트로 바뀐다(뒤로 가기·목록 선택).
  await changeSelectionInPage(page, "/quality-gates?gate=gate-operational-held");
  await expect.poll(() => new URL(page.url()).searchParams.get("gate")).toBe("gate-operational-held");
  // 뒤의 화면은 실제로 다른 게이트로 바뀌었다(주소만 바뀐 것이 아니다).
  await expect(page.locator(".crit-detail-head")).toContainText("gate-operational-held");
  // 그래도 창의 대상과 초안은 그대로다. 저장도 처음 대상으로만 나간다.
  await expect(dialog).toContainText("저장 대상 게이트 · gate-operational-pass");
  await expect(dialog.getByLabel("Pass A 공고 ID · 필수")).toHaveValue("notice-109");
  await dialog.getByRole("button", { name: "근거 리뷰 저장" }).click();

  await expect.poll(() => calls.reviewUpsert.length).toBe(1);
  expect(calls.reviewUpsert[0].gateId).toBe("gate-operational-pass");
});

test("다른 게이트로 연 리뷰 창은 앞 초안을 물려받지 않는다", async ({ page }) => {
  const calls = await open(page, "/quality-gates?gate=gate-operational-pass");
  await detailFooter(page).getByRole("button", { name: "근거 리뷰 작성" }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("Pass A 공고 ID · 필수").fill("notice-109");
  await dialog.getByLabel("리뷰 담당자 · 필수").fill("합성 검토자");
  await dialog.getByLabel("메모 (선택)").fill("합성 메모");
  await dialog.getByRole("button", { name: "취소" }).click();
  await expect(dialog).toBeHidden();

  await changeSelectionInPage(page, "/quality-gates?gate=gate-operational-held");
  await detailFooter(page).getByRole("button", { name: "근거 리뷰 작성" }).click();
  await expect(dialog).toContainText("저장 대상 게이트 · gate-operational-held");
  await expect(dialog.getByLabel("Pass A 공고 ID · 필수")).toHaveValue("");
  await expect(dialog.getByLabel("리뷰 담당자 · 필수")).toHaveValue("");
  await expect(dialog.getByLabel("메모 (선택)")).toHaveValue("");
  expect(calls.reviewUpsert).toHaveLength(0);
});

test("긴 한글 절 제목에서도 목록과 상세가 가로로 넘치지 않는다", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 });
  await open(page, "/profile?psection=capability", { longTitle: true });
  await expect(page.locator(".crit-detail-head")).toContainText(LONG_SECTION_TITLE);
  const overflow = await page.locator(".crit-workspace").evaluate((node) => node.scrollWidth - node.clientWidth);
  expect(overflow).toBeLessThanOrEqual(1);
  await expect(detailFooter(page)).toBeInViewport();
});
