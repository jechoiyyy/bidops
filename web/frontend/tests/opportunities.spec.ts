import { expect, test } from "@playwright/test";
import { mockApi } from "./api-mock";
import { FIXTURES, mockOpportunities } from "./opportunities-fixtures";

test.beforeEach(async ({ page }) => {
  await mockApi(page);
});

test("추적을 선택했지만 사유·기록자가 없으면 미선택으로 바꾸지 않는다", async ({ page }) => {
  await mockOpportunities(page);
  const stored = FIXTURES.find((item) => item.id === 101)!;
  await page.route(/\/api\/opportunities\/101(?:\?.*)?$/, (route) => route.fulfill({
    json: { ...stored, tracking_reason: null, tracking_selected_by: null },
  }));
  await page.goto("/opportunities");
  const footer = page.locator(".opportunity-action-footer");
  await expect(footer).toContainText("계속 추적");
  await expect(footer).toContainText("결정 기록자 미확인");
  await expect(footer).not.toContainText("아직 사람이 선택하지 않음");
  await page.getByRole("tab", { name: "최근 추적 결정", exact: true }).click();
  await expect(page.locator("#opportunity-panel-decision")).toContainText("선택 사유 미확인");
});

// ---------------------------------------------------------------------------
// 목록

// 탐색과 추적 목록 4화면은 상단바가 제목과 화면 액션을 갖고 페이지는 제목 줄을 두지
// 않는다(사용자 결정 2026-09-08). 액션은 페이지 상태(대화상자 열림)를 쓰므로 셸로
// 올리지 않고 `#page-header-actions` portal로 간다.
test("목록은 상단바 제목 모드로 열리고 데이터 현황이 상단바 안에 있다", async ({ page }) => {
  await mockOpportunities(page);
  await page.goto("/opportunities");

  const topbar = page.locator("header.topbar");
  await expect(topbar).toHaveAttribute("data-topbar-mode", "title");
  await expect(topbar.locator("h1")).toHaveText("사업 추적");
  // 같은 이름을 세로로 두 번 쓰지 않는다. 경로와 편집 범위 칩도 제목 모드에는 없다.
  await expect(page.locator(".opportunity-page-header")).toHaveCount(0);
  await expect(page.locator(".topbar-breadcrumb")).toHaveCount(0);
  await expect(page.locator(".topbar-crumb")).toHaveCount(0);
  await expect(page.locator(".topbar-status")).toHaveCount(0);

  const dataStatus = topbar.getByRole("button", { name: "데이터 현황" });
  await expect(dataStatus).toBeVisible();
  await dataStatus.click();
  await expect(page.getByRole("dialog")).toContainText("구역 건수는 서버가 센");
});

test("목록 workspace는 page canvas의 남은 높이를 채운다", async ({ page }) => {
  await mockOpportunities(page);

  for (const viewport of [{ width: 1280, height: 800 }, { width: 1440, height: 900 }]) {
    await page.setViewportSize(viewport);
    await page.goto("/opportunities");
    await expect(page.locator(".opportunity-workspace")).toBeVisible();

    const metrics = await page.evaluate(() => {
      const canvas = document.querySelector(".page-canvas") as HTMLElement;
      const pageRoot = document.querySelector(".opportunities-page") as HTMLElement;
      const workspace = document.querySelector(".opportunity-workspace") as HTMLElement;
      const canvasBox = canvas.getBoundingClientRect();
      const pageBox = pageRoot.getBoundingClientRect();
      const workspaceBox = workspace.getBoundingClientRect();
      const canvasStyle = getComputedStyle(canvas);
      const uiScale = Number.parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--bo-ui-scale")) || 1;
      const contentBottom = canvasBox.bottom - Number.parseFloat(canvasStyle.paddingBottom) * uiScale;
      return {
        contentBottom,
        pageBottom: pageBox.bottom,
        workspaceBottom: workspaceBox.bottom,
        workspaceHeight: workspaceBox.height,
      };
    });

    expect(metrics.pageBottom, `${viewport.width}px page canvas 남은 높이`).toBeCloseTo(metrics.contentBottom, 0);
    expect(metrics.workspaceBottom, `${viewport.width}px workspace 하단`).toBeCloseTo(metrics.pageBottom, 0);
    expect(metrics.workspaceHeight, `${viewport.width}px workspace 높이`).toBeGreaterThan(0);
  }
});

// 상세는 목록으로 돌아갈 경로가 필요하므로 경로 모드로 남는다.
test("단독 상세는 목록으로 돌아갈 경로 표시를 그대로 갖는다", async ({ page }) => {
  await mockOpportunities(page);
  await page.goto("/opportunities/501");

  const topbar = page.locator("header.topbar");
  await expect(topbar).toHaveAttribute("data-topbar-mode", "breadcrumb");
  await expect(topbar.locator(".topbar-breadcrumb .topbar-crumb")).toHaveText([
    "탐색과 추적",
    "사업 추적",
    "#501",
  ]);
  await expect(topbar.getByRole("button", { name: "데이터 현황" })).toHaveCount(0);
});

test("구역 건수는 서버가 센 전체 집합이고 표시 수와 구분된다", async ({ page }) => {
  const trace = await mockOpportunities(page);
  await page.goto("/opportunities");

  await expect(page.locator(".opportunity-list-title")).toHaveText("사업 추적 목록 · 4건");
  const tabs = page.locator(".opportunity-view-tabs button");
  await expect(tabs.nth(0)).toContainText("조치 필요");
  await expect(tabs.nth(0)).toContainText("4");
  await expect(tabs.nth(1)).toContainText("추적 중");
  await expect(tabs.nth(4)).toContainText("전체");
  await expect(tabs.nth(4)).toContainText("8");
  await expect(page.locator(".opportunity-list-foot")).toContainText("불러온 4건 기준 · 4건 표시");
  // 서버가 구역을 정하지 못한 건은 0으로 접지 않고 어디서 보이는지 말한다.
  await expect(page.locator(".opportunity-list-foot")).toContainText("미결정 1건은 전체에서만 보입니다");
  // 기본 구역은 서버 질의로 나간다.
  expect(trace.listQueries.at(-1)?.get("section")).toBe("조치 필요");
});

test("한 사업기회는 구역을 통틀어 한 행으로만 나타난다", async ({ page }) => {
  await mockOpportunities(page);
  const seen: string[] = [];

  for (const section of ["조치 필요", "추적 중", "보류", "추적 종료"]) {
    await page.goto(`/opportunities?section=${encodeURIComponent(section)}`);
    await expect(page.locator(".opportunity-list-title")).toContainText("사업 추적 목록");
    seen.push(...await page.locator(".opportunity-row-title").allInnerTexts());
  }

  expect(new Set(seen).size).toBe(seen.length);
  expect(seen).toContain("공공데이터 통합관리체계 고도화");
  expect(seen).toContain("학사행정시스템 통합 유지관리");
  // 미결정은 어느 구역에도 없다. 전체에서만 보인다.
  expect(seen).not.toContain("공공업무 시스템 개선 용역");
  await page.goto("/opportunities?section=%EC%A0%84%EC%B2%B4");
  await expect(page.locator(".opportunity-row-title", { hasText: "공공업무 시스템 개선 용역" })).toHaveCount(1);
});

test("행은 사업명·기관·최근 확정 단계·추적 상태와 다음 확인 하나를 보여준다", async ({ page }) => {
  await mockOpportunities(page);
  await page.goto("/opportunities");

  const row = page.locator("tbody tr", { hasText: "공공데이터 통합관리체계 고도화" });
  await expect(row.locator(".opportunity-row-agency")).toHaveText("해솔시청");
  await expect(row.locator(".opportunity-row-meta")).toContainText("발주계획");
  await expect(row.locator(".opportunity-row-meta")).toContainText("계속 추적");
  await expect(row.locator(".opportunity-next-cell")).toContainText("연결 후보 확인");
  await expect(row.locator(".opportunity-next-cell")).toContainText("후보 1건");

  const recheck = page.locator("tbody tr", { hasText: "시설관리 업무시스템 구축" });
  await expect(recheck.locator(".opportunity-next-cell")).toContainText("새 공고 재검토");
  await expect(recheck.locator(".opportunity-next-cell")).toContainText("재검토 신호");

  const blocked = page.locator("tbody tr", { hasText: "환경측정 데이터 품질관리 용역" });
  await expect(blocked.locator(".opportunity-next-cell")).toContainText("확인 항목 답변");
  await expect(blocked.locator(".opportunity-next-cell")).toContainText("확인 항목 1건");

  const undecidedRow = page.locator("tbody tr", { hasText: "학교 통합정보서비스" });
  await expect(undecidedRow.locator(".opportunity-next-cell")).toContainText("추적 결정");
  await expect(undecidedRow.locator(".opportunity-row-meta")).toContainText("미선택");
});

test("사업명·기관·행 어디를 눌러도 목록을 떠나지 않고 오른쪽 상세가 바뀐다", async ({ page }) => {
  await mockOpportunities(page);
  await page.goto("/opportunities");
  await expect(page.locator(".opportunity-detail-title")).toHaveText("공공데이터 통합관리체계 고도화");

  // 기관 글자를 눌러도 같은 버튼이 받는다.
  await page.locator("tbody tr", { hasText: "시설관리 업무시스템 구축" }).locator(".opportunity-row-agency").click();
  await expect(page.locator(".opportunity-detail-title")).toHaveText("시설관리 업무시스템 구축");
  await expect(page).toHaveURL(/\/opportunities\?/);
  await expect(page.locator(".opportunity-list-pane tbody tr")).toHaveCount(4);

  // 행의 빈 자리(다음 확인 칸)를 눌러도 선택된다.
  await page.locator("tbody tr", { hasText: "학교 통합정보서비스" }).locator(".opportunity-next-cell").click();
  await expect(page.locator(".opportunity-detail-title")).toHaveText("학교 통합정보서비스 운영 및 유지관리");
  expect(new URL(page.url()).searchParams.get("selected")).toBe("303");
});

// 선택된 행이 눈으로 구분되지 않으면 어떤 사업의 상세를 보고 있는지 알 수 없다.
// 표식이 표가 아니라 행의 선택 버튼에 있으므로 실제 표시를 함께 확인한다.
test("선택한 행은 배경과 왼쪽 강조선으로 표시되고 다른 행을 고르면 함께 옮겨간다", async ({ page }) => {
  await mockOpportunities(page);
  for (const viewport of [{ width: 1280, height: 800 }, { width: 1440, height: 900 }]) {
    await page.setViewportSize(viewport);
    await page.goto("/opportunities");
    await expect(page.locator(".opportunity-detail-title")).toHaveText("공공데이터 통합관리체계 고도화");

    const marks = () => page.evaluate(() => [...document.querySelectorAll("tbody tr")].map((row) => {
      const style = getComputedStyle(row);
      const firstCell = getComputedStyle(row.querySelector("td") as Element);
      return {
        title: row.querySelector(".opportunity-row-title")?.textContent ?? "",
        pressed: row.querySelector(".opportunity-row-business")?.getAttribute("aria-pressed") === "true",
        background: style.backgroundColor,
        accent: firstCell.boxShadow,
      };
    }));

    const first = await marks();
    const selected = first.filter((row) => row.pressed);
    expect(selected, `${viewport.width}px 선택 행`).toHaveLength(1);
    expect(selected[0].title).toBe("공공데이터 통합관리체계 고도화");
    // 선택 행만 배경과 왼쪽 강조선을 갖는다.
    expect(selected[0].background).not.toBe("rgba(0, 0, 0, 0)");
    expect(selected[0].accent).not.toBe("none");
    for (const row of first.filter((entry) => !entry.pressed)) {
      expect(row.background, `${viewport.width}px 비선택 행 배경`).not.toBe(selected[0].background);
      expect(row.accent, `${viewport.width}px 비선택 행 강조선`).toBe("none");
    }

    await page.locator("tbody tr", { hasText: "시설관리 업무시스템 구축" }).locator(".opportunity-row-title").click();
    await expect(page.locator(".opportunity-detail-title")).toHaveText("시설관리 업무시스템 구축");
    const moved = await marks();
    const movedSelection = moved.filter((row) => row.pressed);
    expect(movedSelection).toHaveLength(1);
    expect(movedSelection[0].title).toBe("시설관리 업무시스템 구축");
    // 포인터가 올라간 행은 hover가 겹쳐 색이 미세하게 달라진다. 표시가 옮겨갔는지만 본다.
    expect(movedSelection[0].background).not.toBe("rgba(0, 0, 0, 0)");
    expect(movedSelection[0].accent).toBe(selected[0].accent);
    const previous = moved.find((row) => row.title === "공공데이터 통합관리체계 고도화");
    expect(previous?.accent, `${viewport.width}px 이전 선택 행 강조선`).toBe("none");
  }
});

test("구역·정렬·최초 발견 단계·검색이 주소에 남고 단독 상세에서 되돌아온다", async ({ page }) => {
  const trace = await mockOpportunities(page);
  await page.goto("/opportunities?section=%EB%B3%B4%EB%A5%98&first_registered_stage=order_plan&sort=tracking_status");

  await expect.poll(() => trace.listQueries.some((params) => params.get("section") === "보류"
    && params.get("first_registered_stage") === "order_plan"
    && params.get("sort") === "tracking_status")).toBe(true);
  await expect(page.locator(".opportunity-detail-title")).toHaveText("학사행정시스템 통합 유지관리");

  await page.goto(`/opportunities/606?${new URL(page.url()).searchParams.toString()}`);
  await expect(page.getByRole("heading", { level: 2, name: "사업 추적 상세 #606" })).toBeVisible();
  await page.getByRole("link", { name: "목록으로 →" }).click();
  const listUrl = new URL(page.url());
  expect(listUrl.pathname).toBe("/opportunities");
  expect(listUrl.searchParams.get("section")).toBe("보류");
  expect(listUrl.searchParams.get("sort")).toBe("tracking_status");
  expect(listUrl.searchParams.get("first_registered_stage")).toBe("order_plan");
});

test("검색은 불러온 목록 안에서만 걸리고 빈 결과를 그대로 말한다", async ({ page }) => {
  await mockOpportunities(page);
  await page.goto("/opportunities");

  await page.getByRole("textbox", { name: "사업명·발주기관 검색" }).fill("도담");
  await expect(page.locator("tbody tr")).toHaveCount(1);
  await expect(page.locator(".opportunity-list-foot")).toContainText("불러온 4건 기준 · 1건 표시");
  await expect(page.locator(".opportunity-list-foot")).toContainText("불러온 목록 안에서만 걸립니다");
  // 구역 건수는 검색과 무관한 전체 집합이다.
  await expect(page.locator(".opportunity-view-tabs button").first()).toContainText("4");

  await page.getByRole("textbox", { name: "사업명·발주기관 검색" }).fill("없는사업검색");
  await expect(page.getByRole("heading", { name: "조건에 맞는 사업이 없습니다" })).toBeVisible();
  await expect(page.getByText("사업이 없다는 뜻은 아닙니다")).toBeVisible();
  await page.getByRole("button", { name: "필터 초기화" }).click();
  await expect(page.locator("tbody tr")).toHaveCount(4);
});

test("목록 로딩 실패는 다시 불러오기로 복구한다", async ({ page }) => {
  await mockOpportunities(page, { listStatus: 503 });
  await page.goto("/opportunities");

  await expect(page.getByText("사업 목록을 불러오지 못했습니다.")).toBeVisible();
  await expect(page.getByRole("button", { name: "다시 불러오기" })).toBeVisible();
  await expect(page.locator(".opportunity-detail-pane")).toContainText("선택할 사업이 없습니다");
});

// ---------------------------------------------------------------------------
// 상세 · 사업 흐름

test("3단계 연결 현황은 확정·후보·검색 미확인·연결 미확인을 구분한다", async ({ page }) => {
  await mockOpportunities(page);
  await page.goto("/opportunities/101");

  const stages = page.locator(".opportunity-lifecycle li");
  await expect(stages).toHaveCount(3);
  await expect(stages.nth(0)).toContainText("발주계획");
  await expect(stages.nth(0)).toContainText("공식 연결");
  await expect(stages.nth(0)).toHaveClass(/is-confirmed/);
  await expect(stages.nth(1)).toContainText("사전규격");
  await expect(stages.nth(1)).toContainText("후보 확인 대기");
  await expect(stages.nth(1)).toHaveClass(/is-candidate/);
  await expect(stages.nth(2)).toContainText("입찰공고");
  await expect(stages.nth(2)).toContainText("연결 미확인");
  // 체크는 연결 확정이며 분석 완료나 입찰 승인이 아니다.
  await expect(page.locator(".opportunity-flow-section")).toContainText("연결 확정");
  await expect(page.locator(".opportunity-flow-section")).toContainText("확정된 최근 단계 · 발주계획");

  // 검색 실패 연결에는 원천 레코드가 없어 계약상 단계를 알 수 없다. 화면이 단계를
  // 추정해 채우지 않고, 그 연결이 어디에 있는지 말한다.
  await page.goto("/opportunities/505");
  const unconfirmed = page.locator(".opportunity-lifecycle li").nth(1);
  await expect(unconfirmed).toContainText("연결 미확인");
  await expect(unconfirmed).not.toHaveClass(/is-confirmed/);
  await expect(page.locator(".opportunity-flow-section")).toContainText("단계를 알 수 없는 연결 1건");
});

test("연결된 공고 행은 실제 원천 화면 route로 이동한다", async ({ page }) => {
  await mockOpportunities(page);
  await page.goto("/opportunities/202");

  const rows = page.locator(".opportunity-linked-row");
  await expect(rows).toHaveCount(2);
  await expect(rows.nth(0)).toContainText("DEMO-OP-002");
  await expect(rows.nth(0).getByRole("link", { name: "발주계획 검토목록 열기" })).toHaveAttribute("href", "/order-plans?selected=2001");
  await expect(rows.nth(1).getByRole("link", { name: "공고 판정 이력 열기" })).toHaveAttribute("href", "/judgments/2002");

  await page.goto("/opportunities/404");
  await expect(page.locator(".opportunity-linked-row").getByRole("link", { name: "사전규격 상세 열기" }))
    .toHaveAttribute("href", "/pre-specs/61");
});

test("검색 미확인 연결은 원천 레코드를 만들어 내지 않는다", async ({ page }) => {
  await mockOpportunities(page);
  await page.goto("/opportunities/505");

  const unconfirmedRow = page.locator(".opportunity-linked-row", { hasText: "검색 미확인" });
  await expect(unconfirmedRow).toContainText("일치하는 원천 레코드 미확인");
  await expect(unconfirmedRow).toContainText("이름 검색으로 찾지 못함");
  await expect(unconfirmedRow.getByRole("link")).toHaveCount(0);
  await unconfirmedRow.getByRole("button", { name: "검색 기록" }).click();
  await expect(page.locator(".opportunity-search-log")).toContainText("레코드가 없다는 뜻이 아니며");
  await expect(page.locator(".opportunity-search-log")).toContainText("검색 방식 · normalized");
});

// ---------------------------------------------------------------------------
// 후보 연결 판정

test("후보 연결은 사유·기록자 없이 저장되지 않고 수용하면 확정으로 바뀐다", async ({ page }) => {
  const trace = await mockOpportunities(page);
  await page.goto("/opportunities/101");

  await page.getByRole("button", { name: "후보 연결 확인" }).first().click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toContainText("현재 확정된 연결");
  await expect(dialog).toContainText("이름 검색으로 발견한 후보");
  await expect(dialog).toContainText("자동 확정하지 않습니다");
  // 원천 상세로 가는 길이 대화상자 안에도 있다.
  await expect(dialog.getByRole("link", { name: "발주계획 검토목록 열기 →" })).toHaveAttribute("href", "/order-plans?selected=1001");

  const save = dialog.getByRole("button", { name: "같은 사업으로 연결" });
  await expect(save).toBeDisabled();
  await expect(page.locator("#opportunity-candidate-disabled-reason")).toContainText("판단 사유를 고르거나");

  await dialog.getByRole("combobox", { name: "판단 사유" }).click();
  await page.getByRole("option", { name: "원천 정보를 비교해 같은 사업임을 확인" }).click();
  await expect(save).toBeDisabled();
  await dialog.getByLabel("결정 기록자").fill("홍길동");
  await expect(save).toBeEnabled();
  await save.click();

  await expect(page.getByText("후보 연결을 수용으로 기록했습니다.")).toBeVisible();
  expect(trace.linkDecisions).toHaveLength(1);
  expect(trace.linkDecisions[0].linkId).toBe(1002);
  expect(trace.linkDecisions[0].body).toEqual({
    decision: "accepted",
    reason: "원천 정보를 비교해 같은 사업임을 확인",
  });
  expect(trace.linkDecisions[0].headers["x-bidops-actor-name"]).toBe("UTF-8''%ED%99%8D%EA%B8%B8%EB%8F%99");
  expect(trace.linkDecisions[0].headers["x-bidops-actor-name-format"]).toBe("utf-8-percent-v1");
  // 연결 판정은 추적 상태를 바꾸지 않는다.
  expect(trace.patches).toHaveLength(0);
  await expect(page.locator(".opportunity-lifecycle li").nth(1)).toContainText("사람 확인 완료");
  await expect(page.locator(".opportunity-action-footer")).toContainText("계속 추적");
});

test("기각한 후보는 확정으로 올라가지 않고 이력으로 남는다", async ({ page }) => {
  const trace = await mockOpportunities(page);
  await page.goto("/opportunities/101");

  await page.getByRole("button", { name: "후보 연결 확인" }).first().click();
  const dialog = page.getByRole("dialog");
  await dialog.getByRole("combobox", { name: "연결 판단" }).click();
  await page.getByRole("option", { name: "기각", exact: true }).click();
  await dialog.getByRole("combobox", { name: "판단 사유" }).click();
  await page.getByRole("option", { name: "서로 다른 사업임을 확인" }).click();
  await dialog.getByLabel("결정 기록자").fill("홍길동");
  await dialog.getByRole("button", { name: "후보 기각" }).click();

  await expect(page.getByText("후보 연결을 기각으로 기록했습니다.")).toBeVisible();
  expect(trace.linkDecisions[0].body.decision).toBe("rejected");
  const preSpecStage = page.locator(".opportunity-lifecycle li").nth(1);
  await expect(preSpecStage).toContainText("연결 미확인");
  await expect(preSpecStage).not.toHaveClass(/is-confirmed/);
  await expect(page.locator(".opportunity-linked-row", { hasText: "DEMO-PS-001" })).toContainText("기각");
});

test("후보 판정 실패는 입력을 유지하고 연결이 바뀌지 않았다고 말한다", async ({ page }) => {
  await mockOpportunities(page, { linkDecisionStatus: 409 });
  await page.goto("/opportunities/101");

  await page.getByRole("button", { name: "후보 연결 확인" }).first().click();
  const dialog = page.getByRole("dialog");
  await dialog.getByRole("combobox", { name: "판단 사유" }).click();
  await page.getByRole("option", { name: "공식 식별자 관계를 별도로 확인" }).click();
  await dialog.getByLabel("결정 기록자").fill("홍길동");
  await dialog.getByRole("button", { name: "같은 사업으로 연결" }).click();

  await expect(dialog).toContainText("연결 상태는 바뀌지 않았습니다");
  await expect(dialog.getByLabel("결정 기록자")).toHaveValue("홍길동");
});

// ---------------------------------------------------------------------------
// 추적 상태 변경

test("추적 상태 변경은 사유 선택지와 기타 직접 입력을 갖고 공백을 막는다", async ({ page }) => {
  const trace = await mockOpportunities(page);
  await page.goto("/opportunities/101");

  await page.getByRole("button", { name: "추적 상태 변경" }).click();
  const dialog = page.getByRole("dialog");
  const apply = dialog.getByRole("button", { name: "변경 사항 적용" });
  await expect(apply).toBeDisabled();

  await dialog.getByRole("combobox", { name: "추적 상태" }).click();
  await page.getByRole("option", { name: "보류", exact: true }).click();
  await dialog.getByRole("combobox", { name: "선택 사유" }).click();
  await expect(page.getByRole("option", { name: "예산·일정 추가 확인 필요" })).toBeVisible();
  await page.getByRole("option", { name: "기타", exact: true }).click();

  // 공백만 입력하면 저장할 수 없다.
  await dialog.getByLabel("선택 사유 직접 입력").fill("   ");
  await dialog.getByLabel("결정 기록자").fill("홍길동");
  await expect(apply).toBeDisabled();
  await dialog.getByLabel("선택 사유 직접 입력").fill("요구 범위를 확인한 뒤 재검토");
  await expect(apply).toBeEnabled();
  await apply.click();

  await expect(page.getByText("추적 상태를 저장했습니다.")).toBeVisible();
  expect(trace.patches).toHaveLength(1);
  expect(trace.patches[0].body).toEqual({ tracking_status: "보류", reason: "요구 범위를 확인한 뒤 재검토" });
  expect(trace.patches[0].headers["x-bidops-actor-name"]).toBe("UTF-8''%ED%99%8D%EA%B8%B8%EB%8F%99");
  await expect(page.locator(".opportunity-action-footer")).toContainText("보류");
  // 성공하면 사유 초안이 비워진다. 기록자 이름은 이 브라우저가 기억한다.
  await page.getByRole("button", { name: "추적 상태 변경" }).click();
  await expect(page.getByRole("dialog").getByRole("combobox", { name: "선택 사유" })).toContainText("사유를 선택하세요");
});

test("미선택 건은 화면이 대신 상태를 고르지 않고 미선택으로 되돌릴 수도 없다", async ({ page }) => {
  await mockOpportunities(page);
  await page.goto("/opportunities/303");

  await page.getByRole("button", { name: "추적 여부 선택" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toContainText("아직 아무도 고르지 않았습니다");
  await dialog.getByRole("combobox", { name: "추적 상태" }).click();
  await expect(page.getByRole("option", { name: "미선택" })).toHaveCount(0);
  await expect(page.getByRole("option", { name: "계속 추적" })).toBeVisible();
});

test("입력을 남긴 채 닫으면 버릴지 확인하고 계속 작성하면 초안이 남는다", async ({ page }) => {
  const trace = await mockOpportunities(page);
  await page.goto("/opportunities/101");

  await page.getByRole("button", { name: "추적 상태 변경" }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByRole("combobox", { name: "선택 사유" }).click();
  await page.getByRole("option", { name: "기타", exact: true }).click();
  await dialog.getByLabel("선택 사유 직접 입력").fill("확인 뒤 다시 판단");
  await dialog.getByRole("button", { name: "취소" }).click();

  await expect(dialog).toContainText("입력한 내용을 버릴까요?");
  await dialog.getByRole("button", { name: "계속 작성" }).click();
  await expect(dialog.getByLabel("선택 사유 직접 입력")).toHaveValue("확인 뒤 다시 판단");

  // 저장하지 않은 입력은 화면 이탈도 막는다.
  expect(await page.evaluate(() => {
    const event = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(event);
    return event.defaultPrevented;
  })).toBe(true);

  await dialog.getByRole("button", { name: "취소" }).click();
  await dialog.getByRole("button", { name: "입력 버리고 닫기" }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  expect(trace.patches).toHaveLength(0);
});

test("추적 종료는 확인 없이 요청이 나가지 않고 취소하면 초안만 남는다", async ({ page }) => {
  const trace = await mockOpportunities(page);
  await page.goto("/opportunities/101");

  await page.getByRole("button", { name: "추적 상태 변경" }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByRole("combobox", { name: "추적 상태" }).click();
  await page.getByRole("option", { name: "종료 · 추적 종료" }).click();
  await dialog.getByRole("combobox", { name: "선택 사유" }).click();
  await page.getByRole("option", { name: "사업 방향과 맞지 않음" }).click();
  await dialog.getByLabel("결정 기록자").fill("홍길동");
  await dialog.getByRole("button", { name: "추적 종료로 변경" }).click();

  const confirm = page.getByRole("alertdialog");
  await expect(confirm).toBeVisible();
  await expect(confirm).toContainText("되돌릴 수 없습니다");
  await expect(confirm).toContainText("종료 · 추적 종료");
  await expect(confirm).toContainText("사업 방향과 맞지 않음");
  expect(trace.patches).toHaveLength(0);

  await confirm.getByRole("button", { name: "취소", exact: true }).click();
  expect(trace.patches).toHaveLength(0);
  await expect(page.getByRole("dialog").getByLabel("결정 기록자")).toHaveValue("홍길동");

  await page.getByRole("dialog").getByRole("button", { name: "추적 종료로 변경" }).click();
  await page.getByRole("alertdialog").getByRole("button", { name: "종료 상태로 저장", exact: true }).click();
  await expect(page.getByText("추적 상태를 저장했습니다.")).toBeVisible();
  expect(trace.patches).toHaveLength(1);
  expect(trace.patches[0].body).toEqual({ tracking_status: "종료", reason: "사업 방향과 맞지 않음" });
});

test("추적 저장이 실패하면 초안을 그대로 두고 저장되지 않았다고 말한다", async ({ page }) => {
  await mockOpportunities(page, { trackingStatus: 422 });
  await page.goto("/opportunities/101");

  await page.getByRole("button", { name: "추적 상태 변경" }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByRole("combobox", { name: "선택 사유" }).click();
  await page.getByRole("option", { name: "추가 문서와 요구사항 확인 필요" }).click();
  await dialog.getByLabel("결정 기록자").fill("홍길동");
  await dialog.getByRole("button", { name: "변경 사항 적용" }).click();

  await expect(dialog).toContainText("저장된 추적 상태는 바뀌지 않았습니다");
  await expect(dialog.getByLabel("결정 기록자")).toHaveValue("홍길동");
});

// ---------------------------------------------------------------------------
// 확인 사항 · 최근 추적 결정

test("확인 항목 예외는 회차를 그대로 쓰고 등급·처리 값을 덮지 않는다", async ({ page }) => {
  const trace = await mockOpportunities(page);
  await page.goto("/opportunities/404");

  await page.getByRole("tab", { name: /확인 사항/ }).click();
  const item = page.locator(".opportunity-check-item", { hasText: "확인 항목 답변" });
  await expect(item).toContainText("SW사업자 신고 여부");
  await expect(item).not.toContainText("참고용 유사 실적");
  await expect(item.getByRole("link", { name: "공고 판정 이력 열기 →" })).toBeVisible();

  await item.getByRole("button", { name: "확인 항목 답변 남기기" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toContainText("20260817-20260823--20260824T090927.138116Z");
  await dialog.getByLabel("SW사업자 신고 여부").fill("공고 원문 3쪽에서 SW사업자 신고 대상임을 확인했습니다.");
  await dialog.getByLabel("수정 이유").fill("근거 위치를 확인해 blocking 항목을 해소함");
  await dialog.getByLabel("결정 기록자").fill("홍길동");
  await dialog.getByRole("button", { name: "확인 항목 답변 저장" }).click();

  await expect(page.getByText("확인 항목 답변을 저장했습니다.")).toBeVisible();
  expect(trace.reviewPuts).toHaveLength(1);
  const body = trace.reviewPuts[0].body;
  expect(body.run_id).toBe("20260817-20260823--20260824T090927.138116Z");
  expect(body.reviewer).toBe("홍길동");
  expect(body.verification_answers).toEqual([
    { item: "SW사업자 신고 여부", answer: "공고 원문 3쪽에서 SW사업자 신고 대상임을 확인했습니다." },
  ]);
  expect(body.corrected_grade).toBeNull();
  expect(body.corrected_readiness).toBeNull();
  expect(body.disposition).toBeNull();
  expect(trace.patches).toHaveLength(0);
});

test("재검토 신호는 계산 대기를 결과로 보여주지 않는다", async ({ page }) => {
  await mockOpportunities(page);
  await page.goto("/opportunities/202");

  await page.getByRole("tab", { name: /확인 사항/ }).click();
  const panel = page.locator("#opportunity-panel-checks");
  await expect(panel).toContainText("새 공고 재검토");
  await expect(panel).toContainText("변경 비교 결과 · 계산 대기");
  await expect(panel).toContainText("최종 입찰 참여 판단은 별도의");
  // 변경 비교 화면으로 가는 길은 유지한다.
  await expect(panel.locator('a[href="/opportunities/202/bid-delta"]')).toHaveCount(1);
});

test("확인 사항이 없으면 신호 없음이라고만 말하고 자격 확인으로 읽히지 않게 한다", async ({ page }) => {
  await mockOpportunities(page);
  await page.goto("/opportunities/606");

  await page.getByRole("tab", { name: "확인 사항", exact: true }).click();
  const panel = page.locator("#opportunity-panel-checks");
  await expect(panel).toContainText("현재 등록된 재검토 신호와 연결 예외가 없습니다.");
  await expect(panel).toContainText("참여 자격이나 최종 입찰 가능 여부가 확인됐다는 뜻은 아닙니다.");
  await expect(panel).toContainText("확정된 입찰공고 연결이 없어 변경 비교를 시작할 수 없습니다");
});

test("최근 추적 결정은 API가 주는 가장 최근 한 건만 보여준다", async ({ page }) => {
  const trace = await mockOpportunities(page);
  await page.goto("/opportunities/606");

  await page.getByRole("tab", { name: "최근 추적 결정" }).click();
  const panel = page.locator("#opportunity-panel-decision");
  await expect(panel).toContainText("참여 조건을 추가 확인한 뒤 다시 검토");
  await expect(panel).toContainText("시안 검토자");
  await expect(panel).toContainText("가장 최근 결정 한 건");
  await expect(panel).toContainText("이전 상태 · 계속 추적 → 보류");
  await expect(panel.locator(".opportunity-decision-facts > div")).toHaveCount(3);
  expect(trace.decisionGets).toContain(606);
});

test("결정 기록이 없으면 없다고 말하고 미확인을 값으로 채우지 않는다", async ({ page }) => {
  await mockOpportunities(page, { emptyDecisions: true });
  await page.goto("/opportunities/303");

  await page.getByRole("tab", { name: "최근 추적 결정" }).click();
  const panel = page.locator("#opportunity-panel-decision");
  await expect(panel).toContainText("기록된 추적 결정이 없습니다.");
  await expect(panel).toContainText("아직 아무도 고르지 않았습니다");
  await expect(panel).toContainText("아직 선택하지 않았습니다");
  await expect(panel).toContainText("미확인");
});

test("결정 기록 조회가 실패해도 저장된 값을 결정 기록으로 위장하지 않는다", async ({ page }) => {
  await mockOpportunities(page, { decisionsStatus: 500 });
  await page.goto("/opportunities/606");

  await page.getByRole("tab", { name: "최근 추적 결정" }).click();
  await expect(page.locator("#opportunity-panel-decision")).toContainText("최근 추적 결정 기록을 불러오지 못했습니다");
  await expect(page.locator("#opportunity-panel-decision")).toContainText("결정 기록 자체가 없다는 뜻이 아닙니다");
});

test("심층 검토 보고서 진입점과 계약 한계를 확인 사항에 남긴다", async ({ page }) => {
  await mockOpportunities(page);
  await page.goto("/opportunities/404");

  await page.getByRole("tab", { name: /확인 사항/ }).click();
  const entry = page.locator(".opportunity-deep-review");
  await expect(entry.getByRole("heading", { name: "심층 검토 보고서" })).toBeVisible();
  await expect(entry).toContainText("서버가 사업기회별 보고서 목록을 제공하지 않아");
  await entry.getByLabel("심층 검토 보고서 ID").fill("fixture-review");
  await expect(entry.getByRole("link", { name: "보고서 열기 →" }))
    .toHaveAttribute("href", "/deep-reviews/fixture-review?from=opportunities");
});

test("두 지원 폭에서 가로로 넘치지 않고 상세 바닥 액션이 보인다", async ({ page }) => {
  await mockOpportunities(page);
  for (const viewport of [{ width: 1280, height: 800 }, { width: 1440, height: 900 }]) {
    await page.setViewportSize(viewport);
    await page.goto("/opportunities");
    await expect(page.locator(".opportunity-action-footer")).toBeVisible();
    const metrics = await page.evaluate(() => {
      const footer = document.querySelector(".opportunity-action-footer") as HTMLElement;
      const pane = document.querySelector(".opportunity-list-pane") as HTMLElement;
      const parent = pane.parentElement as HTMLElement;
      return {
        overflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
        footerVisible: footer.getBoundingClientRect().bottom <= window.innerHeight + 1,
        ratio: pane.getBoundingClientRect().width / parent.getBoundingClientRect().width,
      };
    });
    expect(metrics.overflow, `${viewport.width}px 가로 넘침`).toBeLessThanOrEqual(1);
    expect(metrics.footerVisible, `${viewport.width}px 하단 액션`).toBe(true);
    expect(metrics.ratio, `${viewport.width}px 목록 비율`).toBeCloseTo(0.38, 2);
  }
});

test("목록의 글자 크기가 승인된 시안의 15px·14px 단을 지킨다", async ({ page }) => {
  await mockOpportunities(page);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/opportunities");
  await expect(page.locator(".opportunity-row-title").first()).toBeVisible();
  await expect(page.locator(".opportunity-detail-title")).toBeVisible();

  const sizes = await page.evaluate(() => {
    const size = (selector: string) => getComputedStyle(document.querySelector(selector) as Element).fontSize;
    return {
      title: size(".opportunity-row-title"),
      agency: size(".opportunity-row-agency"),
      meta: size(".opportunity-row-meta .opportunity-caption"),
      next: size(".opportunity-next-label"),
      detailTitle: size(".opportunity-detail-title"),
      detailAgency: size(".opportunity-agency-name"),
    };
  });
  expect(sizes.title).toBe("15px");
  expect(sizes.agency).toBe("15px");
  expect(sizes.meta).toBe("14px");
  expect(sizes.next).toBe("14px");
  expect(sizes.detailTitle).toBe("20px");
  // 목록만 15px로 낮췄다. 상세의 발주기관은 시안대로 16px를 유지한다.
  expect(sizes.detailAgency).toBe("16px");
});
