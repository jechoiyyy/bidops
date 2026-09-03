import { expect, test } from "@playwright/test";
import { mockApi, mockOrderPlans } from "./api-mock";

test.beforeEach(async ({ page }) => {
  await mockApi(page);
});

test("기본 목록은 밀집 행이고 판정에 필요한 값만 담으며, 상세 pane의 신호 세부·운영 텔레메트리 탭에 세부 신호가 남는다", async ({ page }) => {
  await mockOrderPlans(page);
  await page.goto("/order-plans");

  await expect(page.locator("section.c2l-page").getByRole("heading", { name: "발주계획 C-2 검토" })).toBeVisible();
  await expect(page.locator(".c2l-row")).toHaveCount(2);
  await expect(page.locator(".c2l-row").first()).toContainText("relevant");
  await expect(page.locator(".c2l-row").nth(1)).toContainText("uncertain");
  await expect(page.locator(".c2l-row").first()).toContainText("125,000,000");
  await expect(page.locator(".c2l-row").first()).not.toContainText("nearest capability");

  // 좁은 뷰포트에서는 상세가 목록을 덮으므로 행을 먼저 명시로 선택한다.
  await page.locator(".c2l-row").first().click();

  // 신호 세부(BM25 rank/score/nearest capability, Qwen score/reason)는 행이 아니라
  // 상세 pane의 별도 탭으로 옮겼다.
  await page.getByRole("tab", { name: "신호 세부" }).click();
  await expect(page.locator("#c2l-panel-signals")).toContainText("nearest capability");
  await expect(page.locator("#c2l-panel-signals")).toContainText("Qwen relevance 신호");

  // 운영 텔레메트리(model_digest, token 수, duration_ms, binding sha256, artifact 요약)도
  // 삭제하지 않고 별도 탭으로 옮겼다.
  await page.getByRole("tab", { name: "운영 텔레메트리" }).click();
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

  await page.getByRole("button", { name: "전체", exact: true }).click();
  await expect(page).toHaveURL(/qwen=(&|$)/);
  await expect(page.locator(".c2l-row")).toHaveCount(8);

  await page.getByRole("button", { name: "BM25 탈락", exact: true }).click();
  await expect(page).toHaveURL(/stage1=filtered_out/);
  await expect(page.locator(".c2l-row")).toHaveCount(1);
  await expect(page.locator(".c2l-row")).toContainText("BM25 탈락");

  // Qwen 비관련은 더 이상 고정 프리셋이 아니라 relevance 축의 한 값이다.
  await page.getByRole("button", { name: "전체", exact: true }).click();
  await page.locator(".c2l-filter-axis", { hasText: "Qwen relevance" }).getByRole("button", { name: "not_relevant" }).click();
  await expect(page).toHaveURL(/qwen=not_relevant/);
  await expect(page.locator(".c2l-row")).toHaveCount(1);
  await expect(page.locator(".c2l-row")).toContainText("not_relevant");

  // "실패·거부" 프리셋은 BM25 단계 실패(106)와 Qwen 단계 실패(105)·거부(108)를 모두 포함하고,
  // Qwen 미시도(104)나 unknown(107)은 포함하지 않는다. 행은 제목이 아니라 상태 문구로 식별한다.
  await page.getByRole("button", { name: "전체", exact: true }).click();
  await page.getByRole("button", { name: "실패·거부", exact: true }).click();
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

  await page.getByRole("button", { name: "전체", exact: true }).click();
  await expect(page.locator(".c2l-row")).toHaveCount(500);
  await expect(page.locator(".c2l-list-head")).toContainText("현재 필터 결과 1,200건");
  await expect(page.locator(".c2l-pager")).toContainText("1–500 / 1,200");
  await page.getByRole("button", { name: "다음", exact: true }).click();
  await expect(page.locator(".c2l-row")).toHaveCount(500);
  await expect(page.locator(".c2l-pager")).toContainText("501–1,000 / 1,200");

  await page.getByRole("button", { name: "실패·거부", exact: true }).click();
  await expect(page.locator(".c2l-row")).toHaveCount(300);
  await expect(page.locator(".c2l-row").first()).toContainText("대규모 페이지네이션 회귀 발주계획 901");
  await expect(page.locator(".c2l-pager")).toHaveCount(0);
});

test("행 선택과 저장은 페이지 이동 0회로 끝나고, 저장 후 다음 이동과 스크롤·선택 유지를 지킨다", async ({ page }) => {
  const trace = await mockOrderPlans(page);
  await page.goto("/order-plans");
  const pathnameBefore = new URL(page.url()).pathname;

  await expect(page.locator(".c2l-row").first()).toContainText("공공데이터 통합");

  // 좁은 뷰포트에서는 행을 명시로 선택해야 상세가 목록을 덮는다(반응형 요구사항).
  await page.locator(".c2l-row").first().click();

  // 사람 피드백 폼은 상세 영역 안에 있다 (판정 탭, 기본 탭). SegmentedControl은 radiogroup으로 렌더된다.
  await page.getByRole("radiogroup", { name: "사람 relevance 판단" }).getByRole("radio", { name: "uncertain" }).click();
  await page.getByLabel("담당자 claimed name").fill("Phase4 tester");
  await page.getByRole("button", { name: "저장 후 다음 →" }).click();

  await expect(page.getByText("저장하고 다음 항목으로 이동했습니다.")).toBeVisible();
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

  // 페이지 이동 0회: pathname이 바뀌지 않는다.
  expect(new URL(page.url()).pathname).toBe(pathnameBefore);

  // 저장 후 다음 이동으로 다음 항목(uncertain, 지방공기업)이 선택된다.
  await expect(page.locator(".c2l-row-wrap.is-selected")).toContainText("지방공기업");
});

test("filtered_out·not_relevant·unknown·null이 서로 바뀌어 표시되지 않는다", async ({ page }) => {
  await mockOrderPlans(page);
  await page.goto("/order-plans");
  await page.getByRole("button", { name: "전체", exact: true }).click();

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
  await page.getByRole("tab", { name: "운영 텔레메트리" }).click();
  await expect(page.locator("#c2l-panel-telemetry")).toContainText("policy/binding 비허용");
});

test("크기 조절 가능한 상세 영역: 드래그와 화살표 키로 폭을 조절하고 localStorage에 남긴다", async ({ page }) => {
  // 960px 미만에서는 목록과 상세가 세로로 쌓이고 separator를 렌더하지 않는다(좁은 폭에서
  // 상세가 목록을 덮는다는 반응형 요구사항). 이 동작은 visual 회귀가 별도로 고정한다.
  const viewport = page.viewportSize();
  test.skip(Boolean(viewport && viewport.width < 960), "960px 미만은 목록/상세가 세로로 쌓이며 separator가 없다");

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
  await page.getByRole("button", { name: "전체", exact: true }).click();
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
  await page.getByRole("button", { name: "검토 대상", exact: true }).click();
  await expect(page.locator(".c2l-row")).toHaveCount(2);

  await page.getByRole("combobox", { name: "저장된 뷰", exact: true }).click();
  await page.getByRole("option", { name: "탈락 확인용" }).click();
  await expect(page.locator(".c2l-row")).toHaveCount(1);
  await expect(page).toHaveURL(/stage1=selected/);
  await expect(page).toHaveURL(/qwen=not_relevant/);
});

test("좁은 폭에서는 상세가 목록을 덮고 ← 목록으로 버튼으로 되돌아간다", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await mockOrderPlans(page);
  await page.goto("/order-plans");

  await expect(page.locator(".c2l-list-pane")).toBeVisible();
  await expect(page.locator(".c2l-detail-pane")).toBeHidden();

  await page.locator(".c2l-row").first().click();
  await expect(page.locator(".c2l-detail-pane")).toBeVisible();
  await expect(page.locator(".c2l-list-pane")).toBeHidden();

  await page.getByRole("button", { name: "← 목록으로" }).click();
  await expect(page.locator(".c2l-list-pane")).toBeVisible();
  await expect(page.locator(".c2l-detail-pane")).toBeHidden();
});

test("사람 피드백 축과 텍스트 검색도 다른 축과 AND로 조합된다", async ({ page }) => {
  await mockOrderPlans(page);
  await page.goto("/order-plans");
  await page.getByRole("button", { name: "전체", exact: true }).click();
  await expect(page.locator(".c2l-row")).toHaveCount(8);

  // 사람 피드백 "있음"은 revision이 있는 101 한 건만 남긴다.
  await page.locator(".c2l-filter-axis", { hasText: "사람 피드백" }).getByRole("button", { name: "있음" }).click();
  await expect(page.locator(".c2l-row")).toHaveCount(1);
  await expect(page.locator(".c2l-row")).toContainText("피드백 rev 1");

  // 필터 초기화 후 텍스트 검색만으로 제목·계획번호를 좁힌다.
  await page.getByRole("button", { name: "필터 초기화" }).click();
  await page.getByRole("button", { name: "전체", exact: true }).click();
  await page.getByLabel("제목·계획번호 검색").fill("지방공기업");
  await page.getByRole("button", { name: "검색", exact: true }).click();
  await expect(page.locator(".c2l-row")).toHaveCount(1);
  await expect(page.locator(".c2l-row")).toContainText("지방공기업");
});

// docs/design/PLAN.md 4단계: 발주계획 상세(사람 relevance·priority·memo 저장,
// 결정 1)도 사전규격 상세·입찰 변경 비교와 같은 골격을 쓴다. 결정 액션은
// 요약 헤더에 고정되어 스크롤 위치와 무관하게 첫 화면에서 보여야 한다.
test("발주계획 상세는 사람 피드백 저장 결정 액션이 헤더에 고정되어 스크롤해도 보인다", async ({ page }) => {
  await mockOrderPlans(page);
  await page.goto("/order-plans/101");
  await expect(page.getByRole("heading", { level: 2 })).toBeVisible();

  const saveButton = page.getByRole("button", { name: "새 revision 저장", exact: true });
  await expect(saveButton).toBeInViewport();
  await expect(page.getByLabel("relevance")).toBeInViewport();
  await expect(page.getByLabel("담당자 claimed name")).toBeInViewport();

  await page.evaluate(() => document.querySelector(".page-canvas")?.scrollTo(0, 999_999));
  await expect(saveButton).toBeInViewport();
});

test("발주계획 상세 헤더는 최근 실행·최근 피드백 상태를 요약하고, 우측 레일은 관측·피드백 이력만 담는다", async ({ page }) => {
  await mockOrderPlans(page);
  await page.goto("/order-plans/101");

  const header = page.locator(".c2-page-header");
  await expect(header.getByText("최근 실행 부분 성공", { exact: true })).toBeVisible();
  await expect(header.getByText("최근 피드백 rev 1", { exact: true })).toBeVisible();

  const rail = page.locator(".detail-skeleton-rail");
  await expect(rail.getByRole("heading", { name: "관측 history", exact: true })).toBeVisible();
  await expect(rail.getByRole("heading", { name: "사람 피드백 revision 이력", exact: true })).toBeVisible();
  await expect(rail.getByRole("link", { name: "발주계획 목록 →", exact: true })).toBeVisible();
  // 결정 액션(저장 버튼)은 헤더에만 있고 레일에는 복제하지 않는다.
  await expect(rail.getByRole("button", { name: "새 revision 저장", exact: true })).toHaveCount(0);
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
