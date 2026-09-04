import { expect, test } from "@playwright/test";
import { mockApi, mockOrderPlans } from "./api-mock";

test.beforeEach(async ({ page }) => {
  await mockApi(page);
});

test("기본 목록은 밀집 행이고 판정에 필요한 값만 담으며, 상세 pane의 신호 세부·실행 기록 탭에 세부 신호가 남는다", async ({ page }) => {
  await mockOrderPlans(page);
  await page.goto("/order-plans");

  await expect(page.locator("section.c2l-page").getByRole("heading", { name: "발주계획 C-2 검토" })).toBeVisible();
  await expect(page.locator(".c2l-row")).toHaveCount(2);
  await expect(page.locator(".c2l-row").first()).toContainText("relevant");
  await expect(page.locator(".c2l-row").nth(1)).toContainText("uncertain");
  await expect(page.locator(".c2l-row").first()).toContainText("125,000,000");
  await expect(page.locator(".c2l-row").first()).not.toContainText("nearest capability");

  // 상세 pane은 행을 고른 뒤에 채워진다.
  await page.locator(".c2l-row").first().click();

  // 신호 세부(BM25 rank/score/nearest capability, Qwen score/reason)는 행이 아니라
  // 상세 pane의 별도 탭으로 옮겼다.
  await page.getByRole("tab", { name: "신호 세부" }).click();
  await expect(page.locator("#c2l-panel-signals")).toContainText("nearest capability");
  await expect(page.locator("#c2l-panel-signals")).toContainText("Qwen relevance 신호");

  // 운영 텔레메트리(model_digest, token 수, duration_ms, binding sha256, artifact 요약)도
  // 삭제하지 않고 `실행 기록` 탭으로 옮겼다.
  await page.getByRole("tab", { name: "실행 기록" }).click();
  await expect(page.locator("#c2l-panel-telemetry")).toContainText("policy/binding");
  await expect(page.locator("#c2l-panel-telemetry")).toContainText("qwen3.8-27B");
  await expect(page.locator("#c2l-panel-telemetry")).toContainText("prompt-v3");
  await expect(page.locator("#c2l-panel-telemetry")).toContainText("profile-v1");
  await expect(page.locator("#c2l-panel-telemetry")).toContainText("qwen_timeout");
  await expect(page.locator("#c2l-panel-telemetry")).toContainText("120,000");
});

test("토큰 필터는 축끼리 AND, 축 안에서는 OR로 조합되고 프리셋은 이름 붙은 지름길일 뿐이다", async ({ page }) => {
  await mockOrderPlans(page);
  await page.goto("/order-plans");

  await page.getByRole("radio", { name: "전체", exact: true }).click();
  await expect(page).toHaveURL(/qwen=(&|$)/);
  await expect(page.locator(".c2l-row")).toHaveCount(8);

  await page.getByRole("radio", { name: "BM25 탈락", exact: true }).click();
  await expect(page).toHaveURL(/stage1=filtered_out/);
  await expect(page.locator(".c2l-row")).toHaveCount(1);
  await expect(page.locator(".c2l-row")).toContainText("BM25 탈락");

  // Qwen 비관련은 더 이상 고정 프리셋이 아니라 relevance 축의 한 값이다.
  await page.getByRole("radio", { name: "전체", exact: true }).click();
  await page.locator(".c2l-filter-axis", { hasText: "Qwen relevance" }).getByRole("button", { name: "not_relevant" }).click();
  await expect(page).toHaveURL(/qwen=not_relevant/);
  await expect(page.locator(".c2l-row")).toHaveCount(1);
  await expect(page.locator(".c2l-row")).toContainText("not_relevant");

  // "실패·거부" 프리셋은 BM25 단계 실패(106)와 Qwen 단계 실패(105)·거부(108)를 모두 포함하고,
  // Qwen 미시도(104)나 unknown(107)은 포함하지 않는다. 행은 제목이 아니라 상태 문구로 식별한다.
  await page.getByRole("radio", { name: "전체", exact: true }).click();
  await page.getByRole("radio", { name: "실패·거부", exact: true }).click();
  await expect(page).toHaveURL(/issue=yes/);
  const issueRows = page.locator(".c2l-row");
  await expect(issueRows).toHaveCount(3);
  await expect(issueRows.filter({ hasText: "BM25 실패" })).toHaveCount(1);
  await expect(issueRows.filter({ hasText: "Qwen 실패" })).toHaveCount(1);
  await expect(issueRows.filter({ hasText: "Qwen 거부" })).toHaveCount(1);
  await expect(issueRows.filter({ hasText: "Qwen unknown" })).toHaveCount(0);

  // 필터 초기화는 검토 대상(기본) 조합으로 되돌린다.
  await page.getByRole("button", { name: "필터 초기화" }).click();
  await expect(page.locator(".c2l-row")).toHaveCount(2);
});

test("1200건 결과에서 기본 review 필터·실패·거부 필터와 페이지 경계를 전체 모집단 기준으로 계산한다", async ({ page }) => {
  await mockOrderPlans(page, "large");
  await page.goto("/order-plans");

  // 기본(review) 필터는 서버가 돌려준 첫 페이지(500건)가 아니라 전체 1,200건 모집단 위에서
  // relevant를 계산한다: index<900은 relevant, 나머지 300은 Qwen 단계 실패라 900건만 남는다.
  // 페이지 하나만 세는 회귀였다면 이 900이라는 숫자가 나오지 않는다.
  await expect(page.locator(".c2l-row")).toHaveCount(500);
  await expect(page.locator(".c2l-list-head")).toContainText("현재 필터 결과 900건");
  await expect(page.locator(".c2l-pager")).toContainText("1–500 / 900");

  await page.getByRole("radio", { name: "전체", exact: true }).click();
  await expect(page.locator(".c2l-row")).toHaveCount(500);
  await expect(page.locator(".c2l-list-head")).toContainText("현재 필터 결과 1,200건");
  await expect(page.locator(".c2l-pager")).toContainText("1–500 / 1,200");
  await page.getByRole("button", { name: "다음", exact: true }).click();
  await expect(page.locator(".c2l-row")).toHaveCount(500);
  await expect(page.locator(".c2l-pager")).toContainText("501–1,000 / 1,200");

  await page.getByRole("radio", { name: "실패·거부", exact: true }).click();
  await expect(page.locator(".c2l-row")).toHaveCount(300);
  await expect(page.locator(".c2l-row").first()).toContainText("대규모 페이지네이션 회귀 발주계획 901");
  await expect(page.locator(".c2l-pager")).toHaveCount(0);
});

test("검토 목록은 고정 높이 안에서 스크롤되고 상세와 같은 높이로 저장 액션을 노출한다", async ({ page }) => {
  await mockOrderPlans(page, "large");
  await page.goto("/order-plans");

  const list = page.locator(".c2l-list-scroll");
  await expect(list).toBeVisible();
  await expect.poll(() => list.evaluate((element) => ({
    clientHeight: element.clientHeight,
    scrollHeight: element.scrollHeight,
  }))).toMatchObject({ clientHeight: expect.any(Number), scrollHeight: expect.any(Number) });

  const scrollMetrics = await list.evaluate((element) => ({
    clientHeight: element.clientHeight,
    scrollHeight: element.scrollHeight,
  }));
  expect(scrollMetrics.scrollHeight).toBeGreaterThan(scrollMetrics.clientHeight);
  await list.evaluate((element) => element.scrollTo({ top: element.scrollHeight, behavior: "instant" }));
  await expect.poll(() => list.evaluate((element) => element.scrollTop)).toBeGreaterThan(0);

  const geometry = await page.locator(".c2l-workspace").evaluate((workspace) => {
    const listPane = workspace.querySelector<HTMLElement>(".c2l-list-pane");
    const detailPane = workspace.querySelector<HTMLElement>(".c2l-detail-pane");
    const actions = workspace.querySelector<HTMLElement>(".c2l-detail-actions");
    if (!listPane || !detailPane || !actions) throw new Error("발주계획 목록·상세 영역을 찾을 수 없습니다.");
    const listRect = listPane.getBoundingClientRect();
    const detailRect = detailPane.getBoundingClientRect();
    const actionsRect = actions.getBoundingClientRect();
    return {
      listHeight: listRect.height,
      detailHeight: detailRect.height,
      detailBottom: detailRect.bottom,
      actionsBottom: actionsRect.bottom,
    };
  });
  expect(Math.abs(geometry.listHeight - geometry.detailHeight)).toBeLessThanOrEqual(1);
  expect(geometry.actionsBottom).toBeLessThanOrEqual(geometry.detailBottom + 1);

  await page.locator(".c2l-workspace").scrollIntoViewIfNeeded();
  for (const label of ["추적 시작", "보류", "추적 종료", "이번 건 넘기기"]) {
    await expect(page.getByRole("button", { name: label, exact: true })).toBeInViewport();
  }
});

test("사람 판단 수정은 접힌 영역에서 새 revision만 저장하고 추적 상태를 건드리지 않는다", async ({ page }) => {
  const trace = await mockOrderPlans(page);
  await page.goto("/order-plans");
  const pathnameBefore = new URL(page.url()).pathname;

  await expect(page.locator(".c2l-row").first()).toContainText("공공데이터 통합");
  await page.locator(".c2l-row").first().click();

  // 사람 판단 수정은 pane 바닥의 결정이 아니라 접힌 보조 입력이다(ADR-0045 결정 5).
  await page.getByRole("button", { name: "사람 판단 수정 (선택) 열기" }).click();
  await page.getByRole("radiogroup", { name: "사람 relevance 판단" }).getByRole("radio", { name: "uncertain" }).click();
  await page.getByLabel("담당자 claimed name").fill("Phase4 tester");
  await page.getByRole("button", { name: "새 revision 저장", exact: true }).click();

  await expect(page.getByText("사람 피드백 revision을 저장했습니다. 추적 상태는 바뀌지 않았습니다.")).toBeVisible();
  expect(trace.feedbackPosts).toHaveLength(1);
  expect(trace.feedbackPosts[0].body).toMatchObject({
    schema_version: "feedback-create-request.v1",
    producer: "human-review-client",
    consumer: "review-api",
    execution_id: "a2f4d7c1-0a61-4a07-8d2e-7f1d1d010101",
    relevance: "uncertain",
    expected_revision: 1,
  });
  expect(trace.feedbackPosts[0].headers["x-bidops-actor-name"]).toBe("Phase4 tester");

  // 추적 결정 경로로는 아무것도 가지 않았다. 두 결정은 서로 다른 요청이다.
  expect(trace.trackingPosts).toHaveLength(0);
  await expect(page.locator(".c2l-tracking")).toContainText("추적 결정 없음");

  // 페이지 이동 0회이고, 사람 판단 저장은 다음 건으로 이동하지 않는다.
  expect(new URL(page.url()).pathname).toBe(pathnameBefore);
  await expect(page.locator(".c2l-row-wrap.is-selected")).toContainText("공공데이터 통합");
});

// ADR-0045 결정 4·5: 결정 1은 추적 결정이고 사람 판단 수정과 저장 경로를 공유하지 않는다.
// 서버 계약은 아직 없다 — fixture 는 docs/design/order-plan-tracking-contract-request.md §2 의
// wire shape 를 mock 하며 구현 완료의 근거가 아니다.
test("추적 결정은 별도 요청으로 저장되고 선택 즉시 다음 발주계획으로 이동한다", async ({ page }) => {
  const trace = await mockOrderPlans(page);
  await page.goto("/order-plans");
  const pathnameBefore = new URL(page.url()).pathname;

  await page.locator(".c2l-row").first().click();
  await expect(page.locator(".c2l-tracking")).toContainText("미선택은 추적 종료가 아닙니다.");

  const start = page.getByRole("button", { name: "추적 시작", exact: true });
  await expect(start).toBeDisabled();
  await expect(page.getByText("담당자 이름을 입력하면 추적 결정을 기록할 수 있습니다.")).toBeVisible();

  await page.getByLabel("담당자 이름").fill("홍길동");
  await expect(start).toBeEnabled();
  await start.click();

  await expect(page.getByText("추적 상태를 계속 추적(으)로 기록했습니다. 다음 발주계획으로 이동합니다.")).toBeVisible();
  expect(trace.trackingPosts).toHaveLength(1);
  expect(trace.trackingPosts[0].orderPlanPk).toBe(101);
  expect(trace.trackingPosts[0].body).toMatchObject({
    schema_version: "order-plan-tracking-decision-create.v1",
    producer: "order-plan-review-client",
    consumer: "order-plan-review-api",
    tracking_status: "계속 추적",
    reason: "후속 사전규격·공고 확인",
    expected_tracking_status: "미선택",
  });
  // 한글 담당자 이름은 RFC 5987 로 인코딩해 보낸다(기존 actor header 규칙).
  expect(trace.trackingPosts[0].headers["x-bidops-actor-name"]).toBe("UTF-8''%ED%99%8D%EA%B8%B8%EB%8F%99");
  expect(trace.trackingPosts[0].headers["x-bidops-actor-name-format"]).toBe("utf-8-percent-v1");

  // 사람 판단 수정 경로로는 아무것도 가지 않았다.
  expect(trace.feedbackPosts).toHaveLength(0);

  // 페이지 이동 0회이고 다음 건이 선택된다.
  expect(new URL(page.url()).pathname).toBe(pathnameBefore);
  await expect(page.locator(".c2l-row-wrap.is-selected")).toContainText("지방공기업");
});

test("이번 건 넘기기는 아무것도 저장하지 않고 미선택을 종료로 바꾸지 않는다", async ({ page }) => {
  const trace = await mockOrderPlans(page);
  await page.goto("/order-plans");
  await page.locator(".c2l-row").first().click();

  // 담당자 이름 없이도 넘기기는 가능하다. 저장하지 않기 때문이다.
  await page.getByRole("button", { name: "이번 건 넘기기", exact: true }).click();

  await expect(page.getByText("추적 상태를 바꾸지 않고 다음 발주계획으로 이동했습니다. 미선택은 추적 종료가 아닙니다.")).toBeVisible();
  expect(trace.trackingPosts).toHaveLength(0);
  expect(trace.feedbackPosts).toHaveLength(0);
  await expect(page.locator(".c2l-row-wrap.is-selected")).toContainText("지방공기업");
  await expect(page.locator(".c2l-tracking")).toContainText("추적 결정 없음");
});

// 요청안 §7 규칙 2·3. 계약이 없는 현재 서버에서 결정을 눌러도 저장된 것처럼 보이지 않는다.
test("추적 결정 계약이 없으면 계약 미구현으로 표시하고 미선택으로 바꾸지 않는다", async ({ page }) => {
  const trace = await mockOrderPlans(page, "no-tracking-contract");
  await page.goto("/order-plans");
  await page.locator(".c2l-row").first().click();

  const tracking = page.locator(".c2l-tracking");
  await expect(tracking).toContainText("계약 미구현");
  await expect(tracking).not.toContainText("추적 결정 없음");
  await expect(tracking).toContainText("추적 결정을 저장할 서버 계약이 아직 구현되지 않았습니다.");

  for (const label of ["추적 시작", "보류", "추적 종료"]) {
    await expect(page.getByRole("button", { name: label, exact: true })).toBeDisabled();
  }
  // 저장하지 않는 넘기기는 계약이 없어도 쓸 수 있다.
  await expect(page.getByRole("button", { name: "이번 건 넘기기", exact: true })).toBeEnabled();
  expect(trace.trackingPosts).toHaveLength(0);

  // 사람 판단 수정은 계약이 있으므로 계속 저장할 수 있다.
  await page.getByRole("button", { name: "사람 판단 수정 (선택) 열기" }).click();
  await expect(page.getByLabel("담당자 claimed name")).toBeVisible();
});

test("소유 사업기회를 확인하지 못하면 저장을 시도하지 않고 다음 건으로도 이동하지 않는다", async ({ page }) => {
  const trace = await mockOrderPlans(page, "no-owning-opportunity");
  await page.goto("/order-plans");
  await page.locator(".c2l-row").first().click();

  const tracking = page.locator(".c2l-tracking");
  await expect(tracking).toContainText("사업기회 미연결");
  await expect(tracking).not.toContainText("추적 결정 없음");
  await expect(page.getByRole("button", { name: "추적 시작", exact: true })).toBeDisabled();
  await expect(page.getByText("이 발주계획을 소유한 사업기회를 확인하지 못해 추적 결정을 기록할 수 없습니다.").first()).toBeVisible();

  expect(trace.trackingPosts).toHaveLength(0);
  await expect(page.locator(".c2l-row-wrap.is-selected")).toContainText("공공데이터 통합");
});

test("filtered_out·not_relevant·unknown·null이 서로 바뀌어 표시되지 않는다", async ({ page }) => {
  await mockOrderPlans(page);
  await page.goto("/order-plans");
  await page.getByRole("radio", { name: "전체", exact: true }).click();

  const rows = page.locator(".c2l-row");
  await expect(rows).toHaveCount(8);

  // filtered_out(BM25 탈락, 104)과 not_relevant(Qwen 비관련, 103)는 서로 다른 행, 다른 문구다.
  await expect(rows.filter({ hasText: "BM25 탈락" })).toHaveCount(1);
  await expect(rows.filter({ hasText: "not_relevant" })).toHaveCount(1);
  await expect(rows.filter({ hasText: "BM25 탈락" })).not.toContainText("not_relevant");

  // unknown(107 · 정보 부족)은 relevance null과 다른 문구로 남아야 하고, not_attempted(104·106)·
  // failed(105)·rejected(108)와도 서로 바뀌어 표시되지 않는다. relevance가 null이라고 이 넷을
  // 전부 같은 문구로 뭉개면 F1 회귀다.
  await expect(rows.filter({ hasText: "Qwen unknown" })).toHaveCount(1);
  await expect(rows.filter({ hasText: "Qwen unknown" })).not.toContainText("not_relevant");
  await expect(rows.filter({ hasText: "Qwen unknown" })).not.toContainText("Qwen 미시도");
  await expect(rows.filter({ hasText: "Qwen unknown" })).not.toContainText("Qwen 실패");
  await expect(rows.filter({ hasText: "Qwen unknown" })).not.toContainText("Qwen 거부");
  // not_attempted는 104(필터 탈락)와 106(BM25 실패) 두 건이다: 서로 다른 두 건이 같은 stage2
  // 값을 갖는 것은 정상이며, unknown·failed·rejected와 섞이지만 않으면 된다.
  await expect(rows.filter({ hasText: "Qwen 미시도" })).toHaveCount(2);
  await expect(rows.filter({ hasText: "Qwen 실패" })).toHaveCount(1);
  await expect(rows.filter({ hasText: "Qwen 거부" })).toHaveCount(1);

  // 신호 세부 탭에서도 status(stage2_status)와 relevance(null)가 같은 문구로 뭉개지지 않는다.
  await rows.filter({ hasText: "Qwen unknown" }).first().click();
  await page.getByRole("tab", { name: "신호 세부" }).click();
  await expect(page.locator("#c2l-panel-signals")).toContainText("Qwen unknown");
  await expect(page.locator("#c2l-panel-signals")).toContainText("null (값 없음/미적용)");
});

test("실패·결과 없음·중지/비허용 상태를 성공 결과로 바꾸지 않는다", async ({ page }) => {
  await mockOrderPlans(page, "failure");
  await page.goto("/order-plans");
  await expect(page.getByText("검토에 사용할 성공/부분 성공 결과가 없습니다.")).toBeVisible();
  await expect(page.locator(".c2l-execution-empty")).toContainText("실패");

  await mockOrderPlans(page, "no-results");
  await page.goto("/order-plans");
  await expect(page.getByText("C-2 실행 결과가 없습니다.")).toBeVisible();

  await mockOrderPlans(page, "live-disabled");
  await page.goto("/order-plans");
  await page.locator(".c2l-row").first().click();
  await page.getByRole("tab", { name: "실행 기록" }).click();
  await expect(page.locator("#c2l-panel-telemetry")).toContainText("policy/binding 비허용");
});

test("크기 조절 가능한 상세 영역: 드래그와 화살표 키로 폭을 조절하고 localStorage에 남긴다", async ({ page }) => {

  await mockOrderPlans(page);
  await page.goto("/order-plans");

  const separator = page.getByRole("separator", { name: "목록 폭 조절" });
  await expect(separator).toBeVisible();
  await separator.focus();
  const before = await separator.getAttribute("aria-valuenow");
  await page.keyboard.press("ArrowRight");
  await page.keyboard.press("ArrowRight");
  const after = await separator.getAttribute("aria-valuenow");
  expect(Number(after)).toBeGreaterThan(Number(before));

  const stored = await page.evaluate(() => window.localStorage.getItem("bidops.order-plans.listWidth"));
  expect(Number(stored)).toBe(Number(after));

  await page.reload();
  const separatorAfterReload = page.getByRole("separator", { name: "목록 폭 조절" });
  await expect(separatorAfterReload).toHaveAttribute("aria-valuenow", String(after));
});

test("저장된 뷰: 이름 붙여 저장한 조합만 localStorage에 남고 다시 불러와 복원한다", async ({ page }) => {
  await mockOrderPlans(page);
  await page.goto("/order-plans");

  // 프리셋 어디에도 없는 커스텀 조합을 만든다: BM25 selected AND Qwen not_relevant.
  await page.getByRole("radio", { name: "전체", exact: true }).click();
  await page.locator(".c2l-filter-axis", { hasText: "BM25 stage1" }).getByRole("button", { name: "selected", exact: true }).click();
  await page.locator(".c2l-filter-axis", { hasText: "Qwen relevance" }).getByRole("button", { name: "not_relevant" }).click();
  await expect(page.locator(".c2l-row")).toHaveCount(1);

  await page.getByRole("button", { name: "현재 필터를 뷰로 저장" }).click();
  await page.getByLabel("뷰 이름").fill("탈락 확인용");
  await page.getByRole("button", { name: "뷰 저장", exact: true }).click();

  const stored = await page.evaluate(() => window.localStorage.getItem("bidops.order-plans.views"));
  expect(stored).toBeTruthy();
  expect(JSON.parse(stored ?? "[]")).toHaveLength(1);
  expect(JSON.parse(stored ?? "[]")[0]).toMatchObject({ name: "탈락 확인용" });

  // 프리셋 클릭 후에도 저장된 뷰를 다시 골라 복원할 수 있다.
  await page.getByRole("radio", { name: "검토 대상", exact: true }).click();
  await expect(page.locator(".c2l-row")).toHaveCount(2);

  await page.getByRole("combobox", { name: "저장된 뷰", exact: true }).click();
  await page.getByRole("option", { name: "탈락 확인용" }).click();
  await expect(page.locator(".c2l-row")).toHaveCount(1);
  await expect(page).toHaveURL(/stage1=selected/);
  await expect(page).toHaveURL(/qwen=not_relevant/);
});

// ADR-0046 이 지원 폭을 1280~1920px 로 좁히면서, 390px 에서 상세가 목록을 덮고
// "← 목록으로" 로 되돌아오던 동작은 없앴다. 그 자리에 반대 불변식을 고정한다:
// 지원 폭 어디에서도 두 pane 이 함께 남고, 행 선택은 상세 pane 만 제자리에서
// 바꾸며 페이지를 이동하지 않는다(PLAN 단계 B).
test("지원 폭 전체에서 목록과 상세 두 pane이 함께 남고 행 선택은 상세만 제자리에서 바꾼다", async ({ page }) => {
  await mockOrderPlans(page);
  await page.goto("/order-plans");

  const workspace = page.locator('[data-review-primitive="split-workspace"]');
  await expect(workspace).not.toHaveAttribute("data-mobile-view", /.*/);

  for (const width of [1280, 1440, 1920]) {
    await page.setViewportSize({ width, height: 900 });
    await expect(page.locator(".c2l-list-pane"), `${width}px 에서 목록 pane`).toBeVisible();
    await expect(page.locator(".c2l-detail-pane"), `${width}px 에서 상세 pane`).toBeVisible();
  }

  const pathnameBefore = new URL(page.url()).pathname;
  await page.locator(".c2l-row").nth(1).click();
  await expect(page.locator(".c2l-row-wrap.is-selected")).toContainText("지방공기업");
  await expect(page.locator(".c2l-detail-pane")).toContainText("지방공기업");
  // 제자리 pane 교체다. /order-plans/:pk 로 이동하지 않는다.
  expect(new URL(page.url()).pathname).toBe(pathnameBefore);
  await expect(page.locator(".c2l-list-pane")).toBeVisible();
  await expect(page.getByRole("button", { name: "← 목록으로" })).toHaveCount(0);
});

test("사람 피드백 축과 텍스트 검색도 다른 축과 AND로 조합된다", async ({ page }) => {
  await mockOrderPlans(page);
  await page.goto("/order-plans");
  await page.getByRole("radio", { name: "전체", exact: true }).click();
  await expect(page.locator(".c2l-row")).toHaveCount(8);

  // 사람 피드백 "있음"은 revision이 있는 101 한 건만 남긴다.
  await page.locator(".c2l-filter-axis", { hasText: "사람 피드백" }).getByRole("button", { name: "있음" }).click();
  await expect(page.locator(".c2l-row")).toHaveCount(1);
  await expect(page.locator(".c2l-row")).toContainText("피드백 rev 1");

  // 필터 초기화 후 텍스트 검색만으로 제목·계획번호를 좁힌다.
  await page.getByRole("button", { name: "필터 초기화" }).click();
  await page.getByRole("radio", { name: "전체", exact: true }).click();
  await page.getByLabel("제목·계획번호 검색").fill("지방공기업");
  await page.getByRole("button", { name: "검색", exact: true }).click();
  await expect(page.locator(".c2l-row")).toHaveCount(1);
  await expect(page.locator(".c2l-row")).toContainText("지방공기업");
});

// docs/design/PLAN.md 단계 F 작업 1: 발주계획 상세(사람 relevance·priority·memo
// 저장, 결정 1)도 사전규격 상세·입찰 변경 비교와 같은 골격을 쓴다. 결정 **액션**은
// 요약 헤더에 고정되어 스크롤 위치와 무관하게 첫 화면에서 보이고, 되돌릴 수 없는
// 입력 **form**은 헤더에 올라가지 않는다(단계 F 완료 게이트).
test("발주계획 상세는 결정 액션만 헤더에 고정하고 입력 form은 본문에 둔다", async ({ page }) => {
  await mockOrderPlans(page);
  await page.goto("/order-plans/101");
  await expect(page.getByRole("heading", { level: 2 })).toBeVisible();

  const header = page.locator(".c2-page-header");
  const saveButton = header.getByRole("button", { name: "새 revision 저장", exact: true });
  await expect(saveButton).toBeInViewport();
  await expect(header.getByRole("button", { name: "사람 판단 입력으로 이동", exact: true })).toBeInViewport();

  // 입력 필드는 헤더가 아니라 본문 열의 패널 안에 있다.
  await expect(header.locator("textarea")).toHaveCount(0);
  await expect(header.getByLabel("담당자 claimed name")).toHaveCount(0);
  await expect(page.locator(".c2-feedback-panel").getByLabel("담당자 claimed name")).toHaveCount(1);

  await page.evaluate(() => document.querySelector(".page-canvas")?.scrollTo(0, 999_999));
  await expect(saveButton).toBeInViewport();
});

// 시안 `OrderPlanDetail`은 사람 피드백 revision 이력과 새 revision 입력을 본문
// 열에 함께 둔다. 지금 저장하려는 값과 직전 revision을 한눈에 대조해야 하기
// 때문이다. 레일은 관측·실행 이력과 연결만 담는다.
test("발주계획 상세 헤더는 상태를 요약하고, revision 이력은 본문 열, 레일은 관측 이력만 담는다", async ({ page }) => {
  await mockOrderPlans(page);
  await page.goto("/order-plans/101");

  const header = page.locator(".c2-page-header");
  await expect(header.getByText("최근 실행 부분 성공", { exact: true })).toBeVisible();
  await expect(header.getByText("최근 피드백 rev 1", { exact: true })).toBeVisible();

  const feedbackPanel = page.locator(".c2-feedback-panel");
  await expect(feedbackPanel.getByRole("heading", { name: "사람 피드백 revision 이력", exact: true })).toBeVisible();
  await expect(feedbackPanel).toContainText("append-only");

  const rail = page.locator(".detail-skeleton-rail");
  await expect(rail).toHaveAttribute("data-review-primitive", "history-link-rail");
  await expect(rail.getByRole("heading", { name: "관측 history", exact: true })).toBeVisible();
  await expect(rail.getByRole("link", { name: "발주계획 목록 →", exact: true })).toBeVisible();
  // 이력은 본문 열이 소유한다. 레일에 복제하지 않는다.
  await expect(rail.getByRole("heading", { name: "사람 피드백 revision 이력", exact: true })).toHaveCount(0);
  // 결정 액션(저장 버튼)도 레일에 복제하지 않는다.
  await expect(rail.getByRole("button", { name: /revision 저장/ })).toHaveCount(0);
});

test("발주계획 상세는 viewport 바깥으로 넘치지 않는다", async ({ page }) => {
  await mockOrderPlans(page);
  await page.goto("/order-plans/101");
  await expect(page.locator("header.topbar h1")).toHaveText("발주계획 C-2 상세");
  await expect.poll(() => page.evaluate(() => ({
    root: document.documentElement.scrollWidth - document.documentElement.clientWidth,
    canvas: (() => {
      const canvas = document.querySelector<HTMLElement>(".page-canvas");
      return canvas ? canvas.scrollWidth - canvas.clientWidth : 0;
    })(),
  }))).toEqual({ root: 0, canvas: 0 });
});
