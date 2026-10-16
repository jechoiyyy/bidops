import { expect, test } from "@playwright/test";
import { mockApi } from "./api-mock";
import { FIXED_NOW, FIXTURES, FUTURE_NOTICE_DEADLINE, mockOpportunities } from "./opportunities-fixtures";
import { shortDateLabel } from "../src/lib/deadline";

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
  await page.getByRole("tab", { name: "추적 이력", exact: true }).click();
  await expect(page.locator("#opportunity-panel-decision")).toContainText("선택 사유 미확인");
});

// ---------------------------------------------------------------------------
// 목록

// 탐색과 추적 목록 4화면은 상단바가 제목과 화면 액션을 갖고 페이지는 제목 줄을 두지
// 않는다(사용자 결정 2026-09-08). 액션은 페이지 상태(대화상자 열림)를 쓰므로 셸로
// 올리지 않고 `#page-header-actions` portal로 간다.
test("목록은 상단바 제목 모드로 열리고 목록 기준이 상단바 안에 있다", async ({ page }) => {
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

  const dataStatus = topbar.getByRole("button", { name: "목록 기준" });
  await expect(dataStatus).toBeVisible();
  await dataStatus.click();
  await expect(page.getByRole("dialog")).toContainText("구역 건수는 서버가 센");
});

test("목록 workspace는 page canvas의 남은 높이를 채운다", async ({ page }) => {
  await mockOpportunities(page);

  for (const viewport of [{ width: 1280, height: 800 }, { width: 1440, height: 900 }]) {
    await page.setViewportSize(viewport);
    await page.goto("/opportunities");
    await expect(page.locator(".review-split-workspace")).toBeVisible();

    const metrics = await page.evaluate(() => {
      const canvas = document.querySelector(".page-canvas") as HTMLElement;
      const pageRoot = document.querySelector(".opportunities-page") as HTMLElement;
      const workspace = document.querySelector(".review-split-workspace") as HTMLElement;
      const canvasBox = canvas.getBoundingClientRect();
      const pageBox = pageRoot.getBoundingClientRect();
      const workspaceBox = workspace.getBoundingClientRect();
      const canvasStyle = getComputedStyle(canvas);
      const contentBottom = canvasBox.bottom - Number.parseFloat(canvasStyle.paddingBottom);
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
  // 시안 v26의 경로는 `상위 화면 / 레코드`다. 사이드바 1차 분류 칸은 그리지 않는다(ui-spec §1.3).
  await expect(topbar.locator(".topbar-breadcrumb .topbar-crumb")).toHaveText([
    "사업 추적",
    "#501",
  ]);
  await expect(topbar.getByRole("button", { name: "목록 기준" })).toHaveCount(0);
});

test("구역 탭은 신규 입찰공고까지 여섯이고 건수는 서버가 센 값이며 표시 수와 구분된다", async ({ page }) => {
  const trace = await mockOpportunities(page);
  await page.goto("/opportunities");

  await expect(page.locator(".opportunity-list-title")).toHaveText("사업 추적 목록 · 5건");
  // 전체는 미결정까지 모든 구역 건수의 합이다. T1 후속: 보류에 대표 링크가 사전규격이고
  // 마감이 미래인 표본(id 911)이 더해져 보류·전체가 하나씩 늘었다.
  await expect(page.locator(".opportunity-view-tabs button")).toHaveText([
    /^조치 필요\s*5$/, /^추적 중\s*1$/, /^보류\s*2$/, /^추적 종료\s*1$/, /^신규 입찰공고\s*1$/, /^전체\s*11$/,
  ]);
  await expect(page.locator(".opportunity-view-tabs button").first()).toHaveAttribute("aria-pressed", "true");
  await expect(page.locator(".opportunity-list-foot")).toContainText("서버 5건 중 5건 표시");
  // 서버가 구역을 정하지 못한 건은 0으로 접지 않고 어디서 보이는지 말한다.
  await expect(page.locator(".opportunity-list-foot")).toContainText("미결정 1건은 전체에서만 보입니다");
  // 기본 구역은 서버 질의로 나가고 사유·검색어는 보내지 않는다.
  expect(trace.listQueries.at(-1)?.get("section")).toBe("조치 필요");
  expect(trace.listQueries.at(-1)?.has("reason")).toBe(false);
  expect(trace.listQueries.at(-1)?.has("q")).toBe(false);

  await page.locator(".opportunity-view-tabs").getByRole("button", { name: /^신규 입찰공고/ }).click();
  await expect.poll(() => trace.listQueries.at(-1)?.get("section")).toBe("신규 입찰공고");
  expect(new URL(page.url()).searchParams.get("section")).toBe("신규 입찰공고");
  await expect(page.locator(".opportunity-row-title")).toHaveText(["학교 통합정보서비스 운영 및 유지관리"]);
  await expect(page.locator(".opportunity-list-head")).toContainText("신규 입찰공고 전체 1건");
  // 사유 칩은 조치 필요 구역 안의 필터다.
  await expect(page.getByRole("group", { name: "조치 사유" })).toHaveCount(0);
});

test("조치 필요 사유 칩은 서버 reason으로 좁히고 주소에 남으며 다른 구역으로 가면 풀린다", async ({ page }) => {
  const trace = await mockOpportunities(page);
  await page.goto("/opportunities");

  const chips = page.getByRole("group", { name: "조치 사유" });
  // 건수는 서버의 `action_reason_counts`다.
  await expect(chips.getByRole("button")).toHaveText([
    /^새 공고\s*1$/, /^후보 확인\s*1$/, /^병합 확인\s*1$/, /^확인 항목\s*1$/, /^보류 기한 지남\s*1$/,
  ]);
  await chips.getByRole("button", { name: /^병합 확인/ }).click();

  await expect.poll(() => trace.listQueries.at(-1)?.get("reason")).toBe("merge_confirmation");
  expect(trace.listQueries.at(-1)?.get("section")).toBe("조치 필요");
  expect(new URL(page.url()).searchParams.get("reason")).toBe("merge_confirmation");
  await expect(chips.getByRole("button", { name: /^병합 확인/ })).toHaveAttribute("aria-pressed", "true");
  await expect(page.locator(".opportunity-row-title")).toHaveText(["스마트 민원 상담 플랫폼 구축"]);
  await expect(page.locator(".opportunity-list-head")).toContainText("조치 필요 · 병합 확인 전체 1건");

  // 주소만으로 같은 필터가 다시 열린다.
  await page.reload();
  await expect(page.locator(".opportunity-row-title")).toHaveText(["스마트 민원 상담 플랫폼 구축"]);
  expect(trace.listQueries.at(-1)?.get("reason")).toBe("merge_confirmation");

  // 같은 칩을 다시 누르면 풀린다.
  await chips.getByRole("button", { name: /^병합 확인/ }).click();
  await expect.poll(() => new URL(page.url()).searchParams.has("reason")).toBe(false);
  await expect(page.locator(".opportunity-table-scroll tbody tr")).toHaveCount(5);

  // 다른 구역으로 가면 사유 필터를 버리고 보내지 않는다.
  await chips.getByRole("button", { name: /^확인 항목/ }).click();
  await expect.poll(() => new URL(page.url()).searchParams.get("reason")).toBe("blocking_item");
  await page.locator(".opportunity-view-tabs").getByRole("button", { name: /^보류/ }).click();
  await expect.poll(() => trace.listQueries.at(-1)?.get("section")).toBe("보류");
  expect(trace.listQueries.at(-1)?.has("reason")).toBe(false);
  expect(new URL(page.url()).searchParams.has("reason")).toBe(false);
  await expect(page.getByRole("group", { name: "조치 사유" })).toHaveCount(0);
});

// S1 — 대시보드 `마감 임박 추적 건`이 넘기는 두 인자(`deadline_within_days`·`sort=deadline`).
// 상세 필터에 `마감 창` 컨트롤을 새로 만들지 않고 URL로만 받으며, 걸려 있다는 사실은
// 발주계획의 회차 줄과 같은 자리의 문맥 줄 하나가 말하고 거기서 해제한다.
test("URL의 마감 창과 마감 임박순을 서버에 그대로 보내고 문맥 줄에서 해제한다", async ({ page }) => {
  const trace = await mockOpportunities(page);
  await page.goto("/opportunities?section=전체&deadline_within_days=7&sort=deadline");

  await expect.poll(() => trace.listQueries.at(-1)?.get("deadline_within_days")).toBe("7");
  expect(trace.listQueries.at(-1)?.get("sort")).toBe("deadline");
  // 구역 `전체`는 서버 인자를 보내지 않는다 — 기본 구역(`조치 필요`)이 다시 걸리지 않는다.
  expect(trace.listQueries.at(-1)?.has("section")).toBe(false);
  await expect(page.locator(".opportunity-view-tabs button").last()).toHaveAttribute("aria-pressed", "true");
  await expect(page.locator(".opportunity-list-head")).toContainText("전체 · 7일 이내 마감");

  // 정렬 값은 상세 필터에서 사람 말로 읽힌다.
  await page.getByRole("button", { name: "상세 필터", exact: true }).click();
  await expect(page.locator("#opportunity-filter-advanced")).toContainText("마감 임박순");

  const context = page.locator(".opportunity-deadline-context");
  await expect(context).toContainText("7일 이내 마감");
  const before = trace.listQueries.length;
  await context.getByRole("button", { name: "해제", exact: true }).click();
  await expect.poll(() => new URL(page.url()).searchParams.has("deadline_within_days")).toBe(false);
  await expect(page.locator(".opportunity-deadline-context")).toHaveCount(0);
  await expect.poll(() => trace.listQueries.length).toBeGreaterThan(before);
  expect(trace.listQueries.slice(before).every((params) => !params.has("deadline_within_days"))).toBe(true);
  // 창만 푼다 — 정렬은 사람이 고른 값이라 남는다.
  expect(new URL(page.url()).searchParams.get("sort")).toBe("deadline");
});

test("허용 범위 밖의 마감 창은 서버에 보내지 않고 줄도 그리지 않는다", async ({ page }) => {
  const trace = await mockOpportunities(page);
  await page.goto("/opportunities?deadline_within_days=0");
  await expect(page.locator(".opportunity-row-title").first()).toBeVisible();
  expect(trace.listQueries.every((params) => !params.has("deadline_within_days"))).toBe(true);
  await expect(page.locator(".opportunity-deadline-context")).toHaveCount(0);
});

test("한 사업기회는 구역을 통틀어 한 행으로만 나타난다", async ({ page }) => {
  await mockOpportunities(page);
  const seen: string[] = [];

  for (const section of ["조치 필요", "추적 중", "보류", "추적 종료", "신규 입찰공고"]) {
    await page.goto(`/opportunities?section=${encodeURIComponent(section)}`);
    await expect(page.locator(".opportunity-list-title")).toContainText("사업 추적 목록");
    seen.push(...await page.locator(".opportunity-row-title").allInnerTexts());
  }

  expect(new Set(seen).size).toBe(seen.length);
  expect(seen).toContain("공공데이터 통합관리체계 고도화");
  expect(seen).toContain("학사행정시스템 통합 유지관리");
  expect(seen).toContain("학교 통합정보서비스 운영 및 유지관리");
  // 미결정은 어느 구역에도 없다. 전체에서만 보인다.
  expect(seen).not.toContain("공공업무 시스템 개선 용역");
  await page.goto("/opportunities?section=%EC%A0%84%EC%B2%B4");
  await expect(page.locator(".opportunity-row-title", { hasText: "공공업무 시스템 개선 용역" })).toHaveCount(1);
});

test("행은 사업명·기관·단계 줄에 사유 칩과 사유별 주 행동 하나를 붙이고 보류 기한은 한국 시간 날짜 차이로 적는다", async ({ page }) => {
  await page.clock.setFixedTime(FIXED_NOW);
  await mockOpportunities(page);
  await page.goto("/opportunities");
  const row = (title: string) => page.locator(".opportunity-table-scroll tbody tr", { hasText: title });

  const candidate = row("공공데이터 통합관리체계 고도화");
  await expect(candidate.locator(".opportunity-row-agency")).toHaveText("해솔시청");
  await expect(candidate.locator(".opportunity-row-meta")).toContainText("발주계획");
  await expect(candidate.locator(".opportunity-row-meta")).toContainText("계속 추적");
  await expect(candidate.locator(".opportunity-next-cell")).toContainText("연결 후보 확인");
  await expect(candidate.locator(".opportunity-next-cell")).toContainText("후보 1건");
  // F3(spec §6.3): 대표 링크(id 1001, 발주계획)의 예산·발주 예정을 그 값 그대로 붙인다.
  await expect(candidate.locator(".opportunity-row-meta")).toContainText("950,000,000원 · 발주 예정 2026년 11월");

  const expected = [
    { title: "공공데이터 통합관리체계 고도화", chips: ["후보 확인"], action: "후보 확인" },
    { title: "시설관리 업무시스템 구축", chips: ["새 공고"], action: "확인" },
    { title: "환경측정 데이터 품질관리 용역", chips: ["확인 항목"], action: "확인 사항 열기" },
    { title: "스마트 민원 상담 플랫폼 구축", chips: ["병합 확인"], action: "후보 확인" },
    // 기한 2026-09-15 10:00 KST, 기준 2026-09-17 12:00 KST.
    { title: "도시계획 정보체계 유지관리", chips: ["보류 기한 지남 D+2"], action: "재검토" },
  ];
  for (const entry of expected) {
    await expect(row(entry.title).getByRole("list", { name: "조치 사유" }).getByRole("listitem"), entry.title).toHaveText(entry.chips);
    const actions = row(entry.title).locator(".opportunity-next-cell").getByRole("button");
    await expect(actions, entry.title).toHaveText([entry.action]);
  }
  await expect(row("시설관리 업무시스템 구축").locator(".opportunity-next-cell")).toContainText("새 공고 재검토");
  await expect(row("환경측정 데이터 품질관리 용역").locator(".opportunity-next-cell")).toContainText("확인 항목 1건");
  await expect(row("도시계획 정보체계 유지관리").locator(".opportunity-next-cell")).toContainText("보류 재검토");

  // 기한이 남은 보류는 사유가 아니라 중립 캡션이고 주 행동이 없다(기한 2026-09-18 KST → D-1).
  await page.locator(".opportunity-view-tabs").getByRole("button", { name: /^보류/ }).click();
  const held = row("학사행정시스템 통합 유지관리");
  await expect(held.getByRole("list", { name: "조치 사유" }).getByRole("listitem")).toHaveText(["보류 기한 D-1"]);
  await expect(held.locator(".opportunity-row-hold")).toHaveCount(1);
  await expect(held.locator(".opportunity-next-cell").getByRole("button")).toHaveCount(0);

  // 사유가 없는 미선택 행은 칩도 주 행동도 없다.
  await page.locator(".opportunity-view-tabs").getByRole("button", { name: /^신규 입찰공고/ }).click();
  const unselected = row("학교 통합정보서비스");
  await expect(unselected.locator(".opportunity-next-cell")).toContainText("추적 결정");
  await expect(unselected.locator(".opportunity-row-meta")).toContainText("미선택");
  await expect(unselected.getByRole("list", { name: "조치 사유" })).toHaveCount(0);
  await expect(unselected.locator(".opportunity-next-cell").getByRole("button")).toHaveCount(0);
  // F3: 대표 링크(id 3001, 공고)에 예산·마감 값이 없으면 `미확인`이 아니라
  // `미제공`이다(서버가 null을 준 것, spec §1.1).
  await expect(unselected.locator(".opportunity-row-meta")).toContainText("예산 미제공 · 마감 미제공");
});

// F3(spec §6.3): 대표 링크가 공고(bid_notice)이고 예산·마감 값이 있는 경우. 이 공유
// mock(`api-mock.ts`의 기본 `mockOpportunity`, `mockApi`가 등록)이 주는 사업기회
// 501("최종 결정 대기 사업")은 단일 링크만 갖고 있어 예산 430,000,000원·
// 마감 2026-09-18의 공고가 그대로 대표 링크다. 그 날짜는 항상 과거이므로(실행
// 시각과 무관하게 안정적) `입찰 마감 지남 · MM-DD`을 기대값으로 그대로 쓴다.
test("대표 링크가 공고면 예산·입찰 마감을 그 값 그대로 보인다", async ({ page }) => {
  await page.goto("/opportunities");
  await page.locator(".opportunity-view-tabs").getByRole("button", { name: /^추적 중/ }).click();
  const row = page.locator(".opportunity-table-scroll tbody tr", { hasText: "최종 결정 대기 사업" });
  await expect(row.locator(".opportunity-row-meta")).toContainText(
    `430,000,000원 · 입찰 마감 지남 · ${shortDateLabel("2026-09-18T00:00:00Z")}`,
  );
});

// T1 후속(F3 spec §6.3): 대표 링크가 사전규격이고 마감이 아직 남은 경우. 위 표본(501)은
// 마감이 항상 지났으므로 D-n(미래) 가지가 덮이지 않았다. id 911의 `deadline_at`은
// 실행 시각 기준 `+5일`이라 "오늘" 값과 무관하게 `describeDeadline`과 같은 계산으로
// D-n을 다시 만든다(하드코딩한 `D-5`는 실행이 날짜를 넘기면 흔들린다).
test("대표 링크가 사전규격이고 마감이 남아 있으면 예산·의견 마감을 D-n으로 보인다", async ({ page }) => {
  await mockOpportunities(page);
  await page.goto("/opportunities");
  await page.locator(".opportunity-view-tabs").getByRole("button", { name: /^보류/ }).click();
  const row = page.locator(".opportunity-table-scroll tbody tr", { hasText: "교통정보 수집·제공 플랫폼 고도화" });
  const days = Math.ceil((new Date(FUTURE_NOTICE_DEADLINE).getTime() - Date.now()) / 86_400_000);
  await expect(row.locator(".opportunity-row-meta")).toContainText(`780,000,000원 · 의견 마감 D-${days}`);
});

test("사유가 여럿이면 칩은 표기 순서로 모두 보이고 주 행동은 우선순위 하나다", async ({ page }) => {
  await mockOpportunities(page);
  const stored = FIXTURES.find((item) => item.id === 404)!;
  // 서버 순서가 우선순위와 다르게 와도 화면이 고르는 주 행동은 새 공고(`확인`)다.
  const item = { ...stored, action_reasons: ["blocking_item", "hold_overdue", "candidate_pending", "new_link"], hold_review_due_at: null };
  await page.route(/\/api\/opportunities\?/, (route) => route.fulfill({
    json: {
      items: [item],
      section_counts: { "조치 필요": 1, "추적 중": 0, "보류": 0, "추적 종료": 0, "신규 입찰공고": 0, "미결정": 0 },
      action_reason_counts: { new_link: 1, candidate_pending: 1, merge_confirmation: 0, blocking_item: 1, hold_overdue: 1 },
      total: 1,
      limit: 100,
      offset: 0,
    },
  }));
  await page.goto("/opportunities");

  const row = page.locator(".opportunity-table-scroll tbody tr");
  // 기한 값이 없으면 D±n을 만들어 내지 않는다.
  await expect(row.getByRole("list", { name: "조치 사유" }).getByRole("listitem")).toHaveText(["새 공고", "후보 확인", "확인 항목", "보류 기한 지남"]);
  await expect(row.locator(".opportunity-next-cell").getByRole("button")).toHaveText(["확인"]);
  await expect(row.locator(".opportunity-next-cell")).toContainText("새 공고 재검토");
  // 병합 확인 칩 건수 0은 값 없음이 아니라 실제 0이다.
  await expect(page.getByRole("group", { name: "조치 사유" }).getByRole("button", { name: /^병합 확인/ })).toHaveText(/^병합 확인\s*0$/);
});

test("행의 주 행동은 사유에 맞는 상세 자리를 연다", async ({ page }) => {
  await mockOpportunities(page);
  await page.goto("/opportunities");
  const row = (title: string) => page.locator(".opportunity-table-scroll tbody tr", { hasText: title });

  // 새 공고 → 상세의 확인 사항.
  await row("시설관리 업무시스템 구축").locator(".opportunity-next-cell").getByRole("button", { name: "확인", exact: true }).click();
  await expect(page.locator(".opportunity-detail-title")).toHaveText("시설관리 업무시스템 구축");
  expect(new URL(page.url()).searchParams.get("selected")).toBe("202");
  await expect(page.getByRole("tab", { name: /확인 사항/ })).toHaveAttribute("aria-selected", "true");
  await expect(page.locator(".opportunity-recheck-item")).toContainText("새 공고 재검토");

  // 병합 확인 → 그 후보의 후보 연결 확인 대화상자.
  await row("스마트 민원 상담 플랫폼 구축").locator(".opportunity-next-cell").getByRole("button", { name: "후보 확인", exact: true }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toContainText("공식 번호로 이어진 병합 확인 후보");
  await expect(dialog).toContainText("검색 방식 · 공식 번호 병합 확인");
  await expect(dialog).toContainText("DEMO-BN-009");
  await expect(page.locator(".opportunity-detail-title")).toHaveText("스마트 민원 상담 플랫폼 구축");
  await dialog.getByRole("button", { name: "취소", exact: true }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);

  // 보류 기한 지남 → 추적 상태 대화상자.
  await row("도시계획 정보체계 유지관리").locator(".opportunity-next-cell").getByRole("button", { name: "재검토", exact: true }).click();
  await expect(page.getByRole("dialog", { name: "추적 상태 변경", exact: true })).toBeVisible();
  await expect(page.locator(".opportunity-detail-title")).toHaveText("도시계획 정보체계 유지관리");
});

test("사업명·기관·행 어디를 눌러도 목록을 떠나지 않고 오른쪽 상세가 바뀐다", async ({ page }) => {
  await mockOpportunities(page);
  await page.goto("/opportunities");
  await expect(page.locator(".opportunity-detail-title")).toHaveText("공공데이터 통합관리체계 고도화");

  // 기관 글자를 눌러도 같은 버튼이 받는다.
  await page.locator("tbody tr", { hasText: "시설관리 업무시스템 구축" }).locator(".opportunity-row-agency").click();
  await expect(page.locator(".opportunity-detail-title")).toHaveText("시설관리 업무시스템 구축");
  await expect(page).toHaveURL(/\/opportunities\?/);
  await expect(page.locator(".review-split-list tbody tr")).toHaveCount(5);

  // 행의 빈 자리(다음 확인 칸의 글자)를 눌러도 선택된다. 주 행동 단추는 자기 동작을 한다.
  await page.locator("tbody tr", { hasText: "환경측정 데이터 품질관리 용역" }).locator(".opportunity-next-label").click();
  await expect(page.locator(".opportunity-detail-title")).toHaveText("환경측정 데이터 품질관리 용역");
  expect(new URL(page.url()).searchParams.get("selected")).toBe("404");
});

// 선택된 행이 눈으로 구분되지 않으면 어떤 사업의 상세를 보고 있는지 알 수 없다.
// 표식이 표가 아니라 행의 선택 버튼에 있으므로 실제 표시를 함께 확인한다.
test("선택한 행은 배경으로 표시되고 다른 행을 고르면 함께 옮겨간다", async ({ page }) => {
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
    // 선택 행만 배경을 갖는다(docs/0915_ui-redesign/spec.md §2.3: 좌측 inset 바 없음).
    expect(selected[0].background).not.toBe("rgba(0, 0, 0, 0)");
    for (const row of first.filter((entry) => !entry.pressed)) {
      expect(row.background, `${viewport.width}px 비선택 행 배경`).not.toBe(selected[0].background);
    }

    await page.locator("tbody tr", { hasText: "시설관리 업무시스템 구축" }).locator(".opportunity-row-title").click();
    await expect(page.locator(".opportunity-detail-title")).toHaveText("시설관리 업무시스템 구축");
    const moved = await marks();
    const movedSelection = moved.filter((row) => row.pressed);
    expect(movedSelection).toHaveLength(1);
    expect(movedSelection[0].title).toBe("시설관리 업무시스템 구축");
    // 포인터가 올라간 행은 hover가 겹쳐 색이 미세하게 달라진다. 표시가 옮겨갔는지만 본다.
    expect(movedSelection[0].background).not.toBe("rgba(0, 0, 0, 0)");
    const previous = moved.find((row) => row.title === "공공데이터 통합관리체계 고도화");
    expect(previous?.background, `${viewport.width}px 이전 선택 행 배경`).not.toBe(movedSelection[0].background);
  }
});

test("구역·정렬·최초 발견 단계·검색이 주소에 남고 단독 상세에서 되돌아온다", async ({ page }) => {
  const trace = await mockOpportunities(page);
  await page.goto(`/opportunities?section=%EB%B3%B4%EB%A5%98&first_registered_stage=order_plan&sort=tracking_status&q=${encodeURIComponent("학사행정")}`);

  await expect.poll(() => trace.listQueries.some((params) => params.get("section") === "보류"
    && params.get("first_registered_stage") === "order_plan"
    && params.get("sort") === "tracking_status"
    && params.get("q") === "학사행정")).toBe(true);
  await expect(page.getByRole("textbox", { name: "사업명·발주기관 검색" })).toHaveValue("학사행정");
  await expect(page.locator(".opportunity-detail-title")).toHaveText("학사행정시스템 통합 유지관리");

  await page.goto(`/opportunities/606?${new URL(page.url()).searchParams.toString()}`);
  await expect(page.getByRole("heading", { level: 2, name: "사업 추적 상세 #606" })).toBeVisible();
  await page.getByRole("link", { name: "목록으로 →" }).click();
  const listUrl = new URL(page.url());
  expect(listUrl.pathname).toBe("/opportunities");
  expect(listUrl.searchParams.get("section")).toBe("보류");
  expect(listUrl.searchParams.get("sort")).toBe("tracking_status");
  expect(listUrl.searchParams.get("first_registered_stage")).toBe("order_plan");
  expect(listUrl.searchParams.get("q")).toBe("학사행정");
});

test("검색은 Enter로 서버 q에 적용하고 첫 페이지로 돌아가며 주소에 남는다", async ({ page }) => {
  const trace = await mockOpportunities(page);
  await page.goto("/opportunities?offset=100");
  await expect.poll(() => trace.listQueries.at(-1)?.get("offset")).toBe("100");
  const input = page.getByRole("textbox", { name: "사업명·발주기관 검색" });

  // 두 글자 미만 draft는 적용 전까지 주소·서버 결과를 바꾸지 않는다.
  await input.fill("도");
  await expect.poll(() => new URL(page.url()).searchParams.get("q")).toBeNull();
  await expect(page.locator(".opportunity-table-scroll tbody tr")).toHaveCount(0);
  await input.fill("도담도시");
  await expect.poll(() => new URL(page.url()).searchParams.get("q")).toBeNull();
  await input.press("Enter");
  await expect.poll(() => new URL(page.url()).searchParams.get("q")).toBe("도담도시");
  await expect.poll(() => trace.listQueries.filter((params) => params.has("q")).length).toBe(1);
  const searched = trace.listQueries.filter((params) => params.has("q"));
  expect(searched[0].get("q")).toBe("도담도시");
  // 적용하면 첫 페이지로 간다.
  expect(searched[0].get("offset")).toBe("0");
  expect(new URL(page.url()).searchParams.has("offset")).toBe(false);
  await expect(page.locator(".opportunity-row-title")).toHaveText(["시설관리 업무시스템 구축"]);
  await expect(page.locator(".opportunity-list-head")).toContainText('조치 필요 · 검색 "도담도시" 전체 1건');
  await expect(page.locator(".opportunity-list-foot")).toContainText("서버가 페이지를 나누기 전에 적용합니다");
  await expect(page.getByText("받은 페이지 안에서만")).toHaveCount(0);
  await expect(page.getByText("불러온 목록 안에서만")).toHaveCount(0);

  // 주소의 q로 다시 열면 입력칸과 질의가 그대로다.
  await page.reload();
  await expect(input).toHaveValue("도담도시");
  await expect(page.locator(".opportunity-row-title")).toHaveText(["시설관리 업무시스템 구축"]);
  expect(trace.listQueries.at(-1)?.get("q")).toBe("도담도시");

  await input.fill("없는사업검색");
  await expect(page.locator(".opportunity-row-title")).toHaveText(["시설관리 업무시스템 구축"]);
  await input.press("Enter");
  await expect(page.getByText("조건에 맞는 사업이 없습니다")).toBeVisible();
  await expect(page.getByText('적용된 검색어 "없는사업검색"', { exact: false })).toBeVisible();
  await page.getByRole("button", { name: "검색어만 지우기" }).click();
  await expect(page.locator(".opportunity-table-scroll tbody tr")).toHaveCount(5);
  await expect(input).toHaveValue("");
  expect(new URL(page.url()).searchParams.has("q")).toBe(false);
});

test("목록 로딩 실패는 다시 시도로 복구한다", async ({ page }) => {
  await mockOpportunities(page, { listStatus: 503 });
  await page.goto("/opportunities");

  await expect(page.getByText("사업 목록을 불러오지 못했습니다.")).toBeVisible();
  await expect(page.getByRole("button", { name: "다시 시도" })).toBeVisible();
  await expect(page.locator(".review-split-detail")).toContainText("선택할 사업이 없습니다");
});

// ---------------------------------------------------------------------------
// 목록 키보드 이동 (발주계획·사전규격과 같은 `useRowKeyboardNavigation`)

// 목록은 한 손으로 훑는 자리다. ↑↓가 선택·초점·URL·상세를 함께 옮기지 않으면 사람이
// 매번 마우스로 돌아가야 한다. 리스너는 목록 컨테이너에만 있어 상세 pane의 입력에서
// 누른 방향키는 목록을 움직이지 않는다.
test("목록에서 ↑↓로 행을 옮기면 선택·초점·URL이 함께 따라간다", async ({ page }) => {
  await mockOpportunities(page);
  await page.goto("/opportunities");

  const buttons = page.locator(".opportunity-row-business");
  await expect(buttons).toHaveCount(5);
  await expect(page.locator(".opportunity-detail-title")).toHaveText("공공데이터 통합관리체계 고도화");

  await buttons.first().focus();
  await page.keyboard.press("ArrowDown");
  // 선택은 hook이 아니라 URL이 소유하므로 선택 이동을 먼저 확인한다.
  await expect(buttons.nth(1)).toHaveAttribute("aria-pressed", "true");
  await expect.poll(() => new URL(page.url()).searchParams.get("selected")).toBe("202");
  await expect(buttons.nth(1)).toBeFocused();
  await expect(page.locator(".opportunity-detail-title")).toHaveText("시설관리 업무시스템 구축");

  await page.keyboard.press("ArrowUp");
  await expect(buttons.first()).toHaveAttribute("aria-pressed", "true");
  await expect.poll(() => new URL(page.url()).searchParams.get("selected")).toBe("101");
  await expect(buttons.first()).toBeFocused();
  await expect(page.locator(".opportunity-detail-title")).toHaveText("공공데이터 통합관리체계 고도화");

  // 상세 pane 안에서 누른 방향키는 목록을 움직이지 않는다.
  await page.locator(".opportunity-row-business", { hasText: "시설관리 업무시스템 구축" }).click();
  await page.getByRole("tab", { name: /확인 사항/ }).click();
  await page.locator(".opportunity-recheck-item").getByLabel("결정 기록자").focus();
  await page.keyboard.press("ArrowDown");
  await expect(buttons.nth(1)).toHaveAttribute("aria-pressed", "true");
  expect(new URL(page.url()).searchParams.get("selected")).toBe("202");
});

// 페이지 경계는 hook이 모른다(화면만 offset을 안다). ↓가 페이지 끝에서 멈추면 100건마다
// 사람이 `다음` 버튼을 찾아 마우스로 돌아가야 한다.
test("페이지 경계에서 ↑↓는 앞뒤 페이지의 첫 행·마지막 행으로 이어진다", async ({ page }) => {
  await mockOpportunities(page, { large: true });
  await page.goto("/opportunities");

  const buttons = page.locator(".opportunity-row-business");
  await expect(buttons).toHaveCount(100);
  const lastOfFirstPage = await buttons.nth(99).getAttribute("data-row-key");

  await buttons.nth(99).click();
  await expect(buttons.nth(99)).toHaveAttribute("aria-pressed", "true");
  await buttons.nth(99).focus();
  await page.keyboard.press("ArrowDown");

  await expect.poll(() => new URL(page.url()).searchParams.get("offset")).toBe("100");
  await expect(page.locator(".opportunity-pager")).toContainText("101–125 / 125");
  await expect(buttons).toHaveCount(25);
  await expect(buttons.first()).toHaveAttribute("aria-pressed", "true");
  await expect(buttons.first()).toBeFocused();

  await page.keyboard.press("ArrowUp");
  // 첫 페이지의 offset은 페이저와 같은 방식으로 `0`을 그대로 적는다.
  await expect.poll(() => new URL(page.url()).searchParams.get("offset")).toBe("0");
  await expect(buttons).toHaveCount(100);
  // ↑로 넘어온 사람이 서야 하는 자리는 앞 페이지의 마지막 행이다.
  await expect(buttons.nth(99)).toHaveAttribute("aria-pressed", "true");
  await expect(buttons.nth(99)).toBeFocused();
  await expect.poll(() => new URL(page.url()).searchParams.get("selected")).toBe(lastOfFirstPage);
});

// ↑↓도 행을 바꾸는 조작이다. 마우스 클릭과 다른 문을 열어 두면 저장하지 않은 입력이
// 키보드로만 조용히 사라진다.
test("저장하지 않은 입력이 있으면 ↓ 이동도 확인을 거치고 취소하면 선택이 남는다", async ({ page }) => {
  await mockOpportunities(page);
  await page.goto("/opportunities?selected=202");

  const buttons = page.locator(".opportunity-row-business");
  await expect(buttons.nth(1)).toHaveAttribute("aria-pressed", "true");
  await page.getByRole("tab", { name: /확인 사항/ }).click();
  const card = page.locator(".opportunity-recheck-item");
  await card.getByLabel(/확인 메모/).fill("정정 내용과 기존 검토를 비교함");

  await buttons.nth(1).focus();
  await page.keyboard.press("ArrowDown");
  const dialog = page.getByRole("alertdialog");
  await expect(dialog).toBeVisible();
  await expect(dialog).toContainText("다른 사업기회를 엽니다");

  await page.keyboard.press("Escape");
  await expect(page.getByRole("alertdialog")).toHaveCount(0);
  await expect(buttons.nth(1)).toHaveAttribute("aria-pressed", "true");
  expect(new URL(page.url()).searchParams.get("selected")).toBe("202");
  await expect(card.getByLabel(/확인 메모/)).toHaveValue("정정 내용과 기존 검토를 비교함");
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
  await expect(page.locator(".opportunity-search-log")).toContainText("검색 방식 · 정규화 이름 일치");
  await expect(page.locator(".opportunity-search-log")).toContainText("검색 미확인 · 마지막 검색");
});

test("검색 미확인 기록은 대상마다 가장 최근 것만 남기고 그 뒤에 찾은 같은 대상 후보가 있으면 숨긴다", async ({ page }) => {
  await mockOpportunities(page);
  const stored = FIXTURES.find((item) => item.id === 505)!;
  const [plan, unconfirmed] = stored.links as Array<Record<string, unknown>>;
  // `search_target_kind`는 링크 view 계약에 아직 없는 DB 열이다. 값이 오면 읽고, 오지 않으면
  // 대상을 추정하지 않는다(505 기본 픽스처가 그 경우다).
  const links = [
    plan,
    { ...unconfirmed, id: 5101, search_target_kind: "pre_spec", last_searched_at: "2026-09-06T01:20:00Z" },
    { ...unconfirmed, id: 5102, search_target_kind: "pre_spec", last_searched_at: "2026-09-08T01:20:00Z", attempted_strategies: ["full", "prefix12"] },
    { ...unconfirmed, id: 5103, search_target_kind: "bid_notice", last_searched_at: "2026-09-06T01:20:00Z" },
    {
      ...unconfirmed, id: 5104, status: "후보 확인 대기", search_strategy: "full", agency_match: true,
      last_searched_at: "2026-09-09T00:00:00Z", record_type: "bid_notice", record_id: 5104, notice_id: 5104,
      source_type: "bid_notice", title: "연구성과 통합검색 서비스 개편", agency: "가온연구원",
      external_id: "DEMO-BN-005", record_external_id: "DEMO-BN-005",
    },
  ];
  await page.route(/\/api\/opportunities\/505$/, (route) => route.fulfill({
    json: { ...stored, pending_candidate_link_count: 1, action_reasons: ["candidate_pending"], links },
  }));
  await page.goto("/opportunities/505");

  const lifecycle = page.locator(".opportunity-lifecycle li");
  await expect(lifecycle.nth(1)).toContainText("검색 미확인");
  await expect(lifecycle.nth(2)).toContainText("후보 확인 대기");
  await expect(page.locator(".opportunity-linked-row", { hasText: "검색 미확인" })).toHaveCount(1);

  await page.getByRole("tab", { name: /확인 사항/ }).click();
  const logs = page.locator("#opportunity-panel-checks .opportunity-search-log");
  await expect(logs).toHaveCount(1);
  await expect(logs).toContainText("연결 근거 확인 · 사전규격");
  await expect(logs).toContainText("시도 전체 이름 일치, 앞 12자 일치");
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
// 확인 사항 · 새 공고 확인 · 찾아보기 · 추적 이력

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
  // 회차 식별자 원문은 접힌 `기술 정보`로 내려갔고(ADR-0066 §3.3, 시안 M4) 본문은
  // 어느 회차에 저장하는지를 사람 말로 적는다. 값은 줄이지 않고 전문 그대로다.
  await expect(dialog).toContainText("이 공고가 속한 수집 회차에 저장합니다");
  const runTechnical = dialog.locator("details.deep-review-technical");
  await expect(runTechnical.locator(".deep-review-technical-body")).toBeHidden();
  await runTechnical.locator("summary").click();
  await expect(runTechnical.locator(".deep-review-technical-body"))
    .toContainText("20260817-20260823--20260824T090927.138116Z");
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

test("새 공고 확인 완료는 보던 근거 연결과 메모를 보내고 추적 상태를 바꾸지 않는다", async ({ page }) => {
  const trace = await mockOpportunities(page);
  await page.goto("/opportunities/202");

  await page.getByRole("tab", { name: /확인 사항/ }).click();
  const card = page.locator(".opportunity-recheck-item");
  await expect(card).toContainText("근거 · 입찰공고 · 시설관리 업무시스템 구축 · DEMO-BN-002");
  const done = card.getByRole("button", { name: "확인 완료", exact: true });
  await expect(done).toBeDisabled();
  await card.getByLabel(/확인 메모/).fill("정정 내용과 기존 검토를 비교함");
  await card.getByLabel("결정 기록자").fill("홍길동");
  const decisionsBefore = trace.decisionGets.length;
  await done.click();

  await expect(page.getByText("새 공고 확인을 기록했습니다.")).toBeVisible();
  expect(trace.acks).toHaveLength(1);
  expect(trace.acks[0].id).toBe(202);
  expect(trace.acks[0].body).toEqual({ expected_link_id: 2002, note: "정정 내용과 기존 검토를 비교함" });
  expect(trace.acks[0].headers["x-bidops-actor-name"]).toBe("UTF-8''%ED%99%8D%EA%B8%B8%EB%8F%99");
  // 확인 완료는 추적 상태 저장이 아니다.
  expect(trace.patches).toHaveLength(0);
  await expect(page.locator(".opportunity-recheck-item")).toHaveCount(0);
  await expect(page.locator(".opportunity-action-footer")).toContainText("계속 추적");
  await expect.poll(() => trace.decisionGets.length).toBeGreaterThan(decisionsBefore);

  await page.getByRole("tab", { name: "추적 이력" }).click();
  const newest = page.locator("#opportunity-panel-decision .opportunity-history-item").first();
  await expect(newest).toContainText("확인 완료");
  await expect(newest).toContainText("메모 있음");
  await expect(page.locator("#opportunity-panel-decision")).not.toContainText("정정 내용과 기존 검토를 비교함");
});

test("확인 완료 전에 근거 연결이 바뀌면 최신 상태를 다시 읽는다고 알리고 새 근거를 보여 준다", async ({ page }) => {
  const trace = await mockOpportunities(page, { recheckChanged: true });
  await page.goto("/opportunities/202");

  await page.getByRole("tab", { name: /확인 사항/ }).click();
  const card = page.locator(".opportunity-recheck-item");
  await card.getByLabel("결정 기록자").fill("홍길동");
  const readsBefore = trace.detailGets.filter((id) => id === 202).length;
  await card.getByRole("button", { name: "확인 완료", exact: true }).click();

  await expect(page.locator(".opportunity-recheck-notice")).toContainText("새 공고 근거가 바뀌었습니다. 최신 상태를 다시 읽습니다.");
  await expect.poll(() => trace.detailGets.filter((id) => id === 202).length).toBeGreaterThan(readsBefore);
  await expect(card).toContainText("시설관리 업무시스템 구축 정정공고 · DEMO-BN-002-1");
  expect(trace.acks).toHaveLength(1);
  expect(trace.acks[0].body).toEqual({ expected_link_id: 2002 });
  await expect(page.locator(".opportunity-action-footer")).toContainText("계속 추적");
});

test("재검토 신호가 있으면 추적 상태 대화상자가 저장 시 새 공고 확인도 처리된다고 알린다", async ({ page }) => {
  await mockOpportunities(page);
  await page.goto("/opportunities/202");
  await page.getByRole("button", { name: "추적 상태 변경", exact: true }).click();
  await expect(page.getByRole("dialog")).toContainText("저장하면 새 공고 확인도 함께 처리됩니다.");
  await page.getByRole("dialog").getByRole("button", { name: "취소", exact: true }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);

  await page.goto("/opportunities/101");
  await page.getByRole("button", { name: "추적 상태 변경", exact: true }).click();
  await expect(page.getByRole("dialog")).toContainText("추적 상태·선택 사유·결정 기록자를 함께 남깁니다.");
  await expect(page.getByRole("dialog")).not.toContainText("새 공고 확인도 함께 처리됩니다");
});

test("단계 줄 찾아보기는 기준 레코드가 있는 빈 단계에만 있고 결과 후보를 후보 대화상자로 연다", async ({ page }) => {
  const trace = await mockOpportunities(page);
  const stageSearches = page.locator(".opportunity-lifecycle .opportunity-stage-search");

  // 발주계획·입찰공고 확정 → 사전규격만 찾아본다.
  await page.goto("/opportunities/202");
  await expect(page.locator(".opportunity-lifecycle li").nth(1).getByRole("button", { name: "사전규격 찾아보기" })).toBeVisible();
  await expect(stageSearches).toHaveText(["사전규격 찾아보기"]);
  // 입찰공고만 있으면 기준 레코드가 없어 찾아보기가 없다.
  await page.goto("/opportunities/303");
  await expect(page.locator(".opportunity-lifecycle li")).toHaveCount(3);
  await expect(stageSearches).toHaveCount(0);
  // 사전규격만 있으면 입찰공고만 찾아본다.
  await page.goto("/opportunities/404");
  await expect(stageSearches).toHaveText(["입찰공고 찾아보기"]);
  // 사전규격 후보가 대기 중이면 찾아보기 대신 후보를 본다.
  await page.goto("/opportunities/101");
  await expect(stageSearches).toHaveText(["입찰공고 찾아보기"]);

  await page.goto("/opportunities/606");
  await expect(stageSearches).toHaveText(["사전규격 찾아보기", "입찰공고 찾아보기"]);
  await page.getByRole("button", { name: "사전규격 찾아보기" }).click();
  const panel = page.getByRole("region", { name: "사전규격 찾아보기" });
  const run = panel.getByRole("button", { name: "찾아보기 실행" });
  await expect(run).toBeDisabled();
  expect(trace.searches).toHaveLength(0);
  await panel.getByLabel("결정 기록자").fill("홍길동");
  await run.click();

  const results = panel.getByRole("list", { name: "사전규격 후보" }).getByRole("listitem");
  await expect(results).toHaveCount(2);
  await expect(results.nth(0)).toContainText("학사행정시스템 통합 유지관리 사업");
  await expect(results.nth(0)).toContainText("전체 이름 일치 · 기관 일치");
  await expect(results.nth(1)).toContainText("가장 긴 조각 일치 · 기관 불일치");
  expect(trace.searches).toHaveLength(1);
  expect(trace.searches[0].id).toBe(606);
  expect(trace.searches[0].body).toEqual({ target: "pre_spec" });
  expect(trace.searches[0].headers["x-bidops-actor-name"]).toBe("UTF-8''%ED%99%8D%EA%B8%B8%EB%8F%99");
  // 후보가 생긴 단계는 다시 읽은 연결로 후보 확인 대기가 된다. 확정하지 않는다.
  await expect(page.locator(".opportunity-lifecycle li").nth(1)).toContainText("후보 확인 대기");
  await expect(page.locator(".opportunity-lifecycle li").nth(1)).not.toHaveClass(/is-confirmed/);

  await results.nth(0).getByRole("button", { name: "후보 확인" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toContainText("이름 검색으로 발견한 후보");
  await expect(dialog).toContainText("학사행정시스템 통합 유지관리 사업");
  await expect(dialog).toContainText("검색 방식 · 전체 이름 일치");
  expect(trace.linkDecisions).toHaveLength(0);
});

test("찾아보기가 찾지 못하면 검색 미확인과 마지막 검색 시각을 없음으로 바꾸지 않고 보여 준다", async ({ page }) => {
  const trace = await mockOpportunities(page, { searchScenario: "empty" });
  await page.goto("/opportunities/606");

  await page.getByRole("button", { name: "입찰공고 찾아보기" }).click();
  const panel = page.getByRole("region", { name: "입찰공고 찾아보기" });
  await panel.getByLabel("결정 기록자").fill("홍길동");
  await panel.getByRole("button", { name: "찾아보기 실행" }).click();

  await expect(panel.locator(".opportunity-search-log")).toContainText("검색 미확인 · 마지막 검색 2026.09.17");
  await expect(panel.locator(".opportunity-search-log")).toContainText("레코드가 없다는 뜻이 아닙니다");
  await expect(panel).toContainText("시도한 방식 · 전체 이름 일치, 구분자 분할 일치, 정규화 이름 일치, 가장 긴 조각 일치");
  await expect(panel.getByRole("list")).toHaveCount(0);
  expect(trace.searches[0].body).toEqual({ target: "bid_notice" });

  // 서버에 남은 검색 미확인 기록도 확인 사항에 그대로 남는다.
  await page.getByRole("tab", { name: /확인 사항/ }).click();
  await expect(page.locator("#opportunity-panel-checks .opportunity-search-log")).toContainText("검색 미확인 · 마지막 검색");
});

test("찾아보기 기준 레코드가 서버에 없으면 어떤 원천이 없는지 설명한다", async ({ page }) => {
  const trace = await mockOpportunities(page, { searchScenario: "source_missing" });
  await page.goto("/opportunities/404");

  await page.getByRole("button", { name: "입찰공고 찾아보기" }).click();
  const panel = page.getByRole("region", { name: "입찰공고 찾아보기" });
  await panel.getByLabel("결정 기록자").fill("홍길동");
  const readsBefore = trace.detailGets.filter((id) => id === 404).length;
  await panel.getByRole("button", { name: "찾아보기 실행" }).click();

  await expect(panel).toContainText("소유한 사전규격이나 발주계획이 없어 입찰공고를 찾아볼 기준이 없습니다");
  await expect(panel).not.toContainText("검색 미확인");
  await expect.poll(() => trace.detailGets.filter((id) => id === 404).length).toBeGreaterThan(readsBefore);
  expect(trace.searches[0].body).toEqual({ target: "bid_notice" });
});

test("양쪽에 사람 추적 상태가 있어 병합이 거절되면 두 사업기회의 상태를 보여 주고 입력을 남긴다", async ({ page }) => {
  const trace = await mockOpportunities(page, { linkDecisionMergeConflict: true });
  await page.goto("/opportunities/909");

  await page.locator(".opportunity-action-footer").getByRole("button", { name: "후보 연결 확인" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toContainText("공식 번호로 이어진 병합 확인 후보");
  await dialog.getByRole("combobox", { name: "판단 사유" }).click();
  await page.getByRole("option", { name: "공식 식별자 관계를 별도로 확인" }).click();
  await dialog.getByLabel("결정 기록자").fill("홍길동");
  await dialog.getByRole("button", { name: "같은 사업으로 연결" }).click();

  const conflict = dialog.locator(".opportunity-merge-conflict");
  await expect(conflict).toContainText(
    "두 사업기회의 추적 상태가 다르거나 한쪽에 재검토 신호가 있어 병합할 수 없습니다. 한쪽을 미선택으로 되돌린 뒤 다시 수락하십시오.",
  );
  const states = conflict.getByRole("list", { name: "병합 대상 사업기회의 추적 상태" }).getByRole("listitem");
  await expect(states).toHaveCount(2);
  await expect(states.nth(0)).toContainText("사업 #909 · 계속 추적");
  await expect(states.nth(0)).toContainText("선택자 · 검토 담당자");
  await expect(states.nth(0)).toContainText("재검토 신호 · 없음");
  await expect(states.nth(1)).toContainText("사업 #912 · 보류");
  await expect(states.nth(1)).toContainText("선택자 · 다른 담당자");
  // 신호가 있는 쪽은 언제 온 신호인지까지 말한다(ADR-0068 details 추가 필드).
  await expect(states.nth(1)).toContainText("재검토 신호 · 있음 · 2026.09.09");
  await expect(conflict).toContainText("연결 상태는 바뀌지 않았습니다");
  await expect(dialog.getByLabel("결정 기록자")).toHaveValue("홍길동");
  expect(trace.linkDecisions).toHaveLength(1);
  expect(trace.linkDecisions[0].linkId).toBe(9002);
  expect(trace.linkDecisions[0].body.decision).toBe("accepted");
});

test("병합이 막히면 각 사업을 미선택으로 되돌릴 수 있고 수락은 자동으로 다시 시도되지 않는다", async ({ page }) => {
  const trace = await mockOpportunities(page, { linkDecisionMergeConflict: true });
  await page.goto("/opportunities/909");

  await page.locator(".opportunity-action-footer").getByRole("button", { name: "후보 연결 확인" }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByRole("combobox", { name: "판단 사유" }).click();
  await page.getByRole("option", { name: "공식 식별자 관계를 별도로 확인" }).click();
  await dialog.getByLabel("결정 기록자").fill("홍길동");
  await dialog.getByRole("button", { name: "같은 사업으로 연결" }).click();

  const conflict = dialog.locator(".opportunity-merge-conflict");
  const states = conflict.getByRole("list", { name: "병합 대상 사업기회의 추적 상태" }).getByRole("listitem");
  await expect(states.nth(0).getByRole("button", { name: "사업 #909 미선택으로 되돌리기" })).toBeVisible();
  await expect(states.nth(1).getByRole("button", { name: "사업 #912 미선택으로 되돌리기" })).toBeVisible();

  await states.nth(1).getByRole("button", { name: "사업 #912 미선택으로 되돌리기" }).click();
  const reset = states.nth(1).locator(".opportunity-tracking-reset-open");
  await expect(reset).toContainText("저장된 추적 결정(보류)을 미선택으로 되돌립니다");
  await expect(reset).toContainText("되돌려도 후보 수락은 자동으로 다시 시도하지 않습니다");
  // 담당자는 이 대화상자에서 이미 받았으므로 다시 묻지 않는다.
  await expect(reset).toContainText("결정 기록자 · 홍길동");
  await expect(reset.getByRole("button", { name: "미선택으로 되돌리기 실행" })).toBeDisabled();
  await reset.getByLabel("되돌리는 이유").fill("병합을 위해 한쪽 결정을 정리");
  await reset.getByRole("button", { name: "미선택으로 되돌리기 실행" }).click();

  await expect(conflict).toContainText("미선택으로 되돌렸습니다. 위 상태는 되돌리기 전의 값입니다.");
  await expect(dialog.locator(".opportunity-merge-reset-notice")).toContainText(
    "사업 #912의 추적 결정을 미선택으로 되돌렸습니다. 다시 수락하십시오.",
  );
  expect(trace.patches).toHaveLength(1);
  expect(trace.patches[0].id).toBe(912);
  expect(trace.patches[0].body).toEqual({ tracking_status: "미선택", reason: "병합을 위해 한쪽 결정을 정리" });
  // 비ASCII 담당자 이름은 RFC 5987 인코딩으로 나간다(`utf-8-percent-v1`).
  expect(trace.patches[0].headers["x-bidops-actor-name"]).toBe("UTF-8''%ED%99%8D%EA%B8%B8%EB%8F%99");
  expect(trace.patches[0].headers["x-bidops-actor-name-format"]).toBe("utf-8-percent-v1");
  // 되돌리기는 수락을 다시 보내지 않는다. 두 번째 결정도 사람이 누른다.
  expect(trace.linkDecisions).toHaveLength(1);
  await expect(states.nth(0).getByRole("button", { name: "사업 #909 미선택으로 되돌리기" })).toBeVisible();
  await expect(dialog.getByRole("button", { name: "같은 사업으로 연결" })).toBeEnabled();
});

test("추적 상태가 같아 서버가 병합한 수락은 사람 확인 병합으로 끝난다", async ({ page }) => {
  const trace = await mockOpportunities(page, { linkDecisionMerged: true });
  await page.goto("/opportunities/909");

  await page.locator(".opportunity-action-footer").getByRole("button", { name: "후보 연결 확인" }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByRole("combobox", { name: "판단 사유" }).click();
  await page.getByRole("option", { name: "공식 식별자 관계를 별도로 확인" }).click();
  await dialog.getByLabel("결정 기록자").fill("홍길동");
  await dialog.getByRole("button", { name: "같은 사업으로 연결" }).click();

  await expect(page.getByText("후보를 수용해 두 사업기회를 병합했습니다(사람 확인 병합).")).toBeVisible();
  // 같은 상태 병합에는 막힘 안내가 아예 뜨지 않는다.
  await expect(page.locator(".opportunity-merge-conflict")).toHaveCount(0);
  expect(trace.linkDecisions).toHaveLength(1);
  expect(trace.patches).toHaveLength(0);
});

test("추적 결정 카드에서 결정을 미선택으로 되돌린다", async ({ page }) => {
  const trace = await mockOpportunities(page);
  await page.goto("/opportunities/606");

  await page.getByRole("tab", { name: "추적 이력" }).click();
  const panel = page.locator("#opportunity-panel-decision");
  await expect(panel).toContainText("참여 조건을 추가 확인한 뒤 다시 검토");
  await panel.getByRole("button", { name: "미선택으로 되돌리기", exact: true }).click();

  const reset = panel.locator(".opportunity-tracking-reset-open");
  await expect(reset).toContainText("저장된 추적 결정(보류)을 미선택으로 되돌립니다");
  await expect(reset).toContainText("검토할 항목·조치 필요로 돌아옵니다");
  await expect(reset.getByRole("button", { name: "미선택으로 되돌리기 실행" })).toBeDisabled();
  await reset.getByLabel("되돌리는 이유").fill("상태를 잘못 골라 되돌림");
  await reset.getByLabel("결정 기록자").fill("홍길동");
  await reset.getByRole("button", { name: "미선택으로 되돌리기 실행" }).click();

  await expect(page.getByText("추적 결정을 미선택으로 되돌렸습니다.")).toBeVisible();
  expect(trace.patches).toHaveLength(1);
  expect(trace.patches[0].id).toBe(606);
  expect(trace.patches[0].body).toEqual({ tracking_status: "미선택", reason: "상태를 잘못 골라 되돌림" });
  expect(trace.patches[0].headers["x-bidops-actor-name"]).toBe("UTF-8''%ED%99%8D%EA%B8%B8%EB%8F%99");
  expect(trace.patches[0].headers["x-bidops-actor-name-format"]).toBe("utf-8-percent-v1");
  // 되돌린 뒤에는 되돌릴 결정이 없다고 말하고 단추를 잠근다.
  const disabled = panel.getByRole("button", { name: "미선택으로 되돌리기", exact: true });
  await expect(disabled).toBeDisabled();
  await expect(panel).toContainText("이미 미선택입니다. 되돌릴 추적 결정이 없습니다.");
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

test("추적 이력은 현재 추적 결정 사실을 먼저 보여 주고 결정 revision을 이력으로 남긴다", async ({ page }) => {
  const trace = await mockOpportunities(page);
  await page.goto("/opportunities/606");

  await page.getByRole("tab", { name: "추적 이력" }).click();
  const panel = page.locator("#opportunity-panel-decision");
  await expect(panel).toContainText("참여 조건을 추가 확인한 뒤 다시 검토");
  await expect(panel).toContainText("시안 검토자");
  await expect(panel.locator(".opportunity-decision-facts > div")).toHaveCount(3);
  const items = panel.locator(".opportunity-history-item");
  await expect(items).toHaveCount(1);
  await expect(items).toContainText("계속 추적 → 보류");
  await expect(panel).toContainText("결정 1건 · 재검토 신호 0건");
  expect(trace.decisionGets).toContain(606);
});

test("추적 이력은 결정 revision과 재검토 신호 이벤트를 마이크로초·시간대까지 맞춰 최신순으로 함께 보여 준다", async ({ page }) => {
  await mockOpportunities(page);
  await page.goto("/opportunities/202");

  await page.getByRole("tab", { name: "추적 이력" }).click();
  const items = page.locator("#opportunity-panel-decision .opportunity-history-item");
  await expect(items).toHaveCount(7);
  expect(await items.evaluateAll((nodes) => nodes.map((node) => node.getAttribute("data-history-kind")))).toEqual([
    "recheck", "recheck", "recheck", "recheck", "decision", "recheck", "decision",
  ]);
  // 06T01:30Z 생성
  await expect(items.nth(0)).toContainText("신호 생성");
  await expect(items.nth(0)).toContainText("시스템");
  await expect(items.nth(0)).toContainText("근거 입찰공고 · DEMO-BN-002");
  // 06T09:00+09:00 = 06T00:00Z 확인 완료. 메모는 있었는지만 말한다.
  await expect(items.nth(1)).toContainText("확인 완료");
  await expect(items.nth(1)).toContainText("홍길동");
  await expect(items.nth(1)).toContainText("메모 있음");
  await expect(items.nth(2)).toContainText("신호 생성");
  await expect(items.nth(2)).not.toContainText("메모 있음");
  // 같은 밀리초 안에서 300마이크로초 늦은 해제 이벤트가 결정보다 위다.
  await expect(items.nth(3)).toContainText("결정 저장으로 해제");
  await expect(items.nth(3)).toContainText("검토 담당자");
  await expect(items.nth(4)).toContainText("보류 → 계속 추적");
  await expect(items.nth(4)).toContainText("재검토 신호 함께 해제");
  await expect(items.nth(6)).toContainText("예산·일정 추가 확인 필요");
});

test("결정 기록이 없으면 없다고 말하고 미확인을 값으로 채우지 않는다", async ({ page }) => {
  await mockOpportunities(page, { emptyDecisions: true });
  await page.goto("/opportunities/303");

  await page.getByRole("tab", { name: "추적 이력" }).click();
  const panel = page.locator("#opportunity-panel-decision");
  await expect(panel).toContainText("기록된 추적 결정이 없습니다.");
  await expect(panel).toContainText("기록된 이력이 없습니다.");
  await expect(panel).toContainText("아직 아무도 고르지 않았습니다");
  await expect(panel).toContainText("아직 선택하지 않았습니다");
  await expect(panel).toContainText("미확인");
});

test("결정 기록 조회가 실패해도 저장된 값을 결정 기록으로 위장하지 않는다", async ({ page }) => {
  await mockOpportunities(page, { decisionsStatus: 500 });
  await page.goto("/opportunities/606");

  await page.getByRole("tab", { name: "추적 이력" }).click();
  await expect(page.locator("#opportunity-panel-decision")).toContainText("추적 이력을 불러오지 못했습니다");
  await expect(page.locator("#opportunity-panel-decision")).toContainText("결정 기록 자체가 없다는 뜻이 아닙니다");
});

test("심층 검토 보고서 목록을 API에서 받아 상태·품질 표식·최종 의견과 함께 보여 준다", async ({ page }) => {
  const trace = await mockOpportunities(page);
  await page.goto("/opportunities/404");

  await page.getByRole("tab", { name: /확인 사항/ }).click();
  const entry = page.locator(".opportunity-deep-review");
  await expect(entry.getByRole("heading", { name: "심층 검토 보고서" })).toBeVisible();

  const rows = entry.locator(".opportunity-deep-review-item");
  await expect(rows).toHaveCount(2);

  const completedRow = rows.filter({ hasText: "환경측정 데이터 품질관리 용역" });
  await expect(completedRow).toContainText("완료");
  await expect(completedRow).toContainText("측정 통과");
  await expect(completedRow).toContainText("최종 의견 · 추진");
  await expect(completedRow.getByRole("link", { name: "보고서 열기 →" }))
    .toHaveAttribute("href", "/deep-reviews/d1111111-1111-4111-8111-111111111111?from=opportunities");

  const runningRow = rows.filter({ hasText: "공고명 미확인" });
  await expect(runningRow).toContainText("진행 중");
  await expect(runningRow).toContainText("표식 없음");
  await expect(runningRow).toContainText("최종 의견 없음");
  await expect(runningRow.getByRole("link", { name: "보고서 열기 →" }))
    .toHaveAttribute("href", "/deep-reviews/d2222222-2222-4222-8222-222222222222?from=opportunities");

  expect(trace.deepReviewGets).toContain(404);
});

test("연결된 심층 검토 보고서가 없으면 빈 상태를 보여주고 목록을 지어내지 않는다", async ({ page }) => {
  await mockOpportunities(page);
  await page.goto("/opportunities/606");

  await page.getByRole("tab", { name: /확인 사항/ }).click();
  const entry = page.locator(".opportunity-deep-review");
  await expect(entry.getByRole("heading", { name: "심층 검토 보고서" })).toBeVisible();
  await expect(entry).toContainText("연결된 심층 검토 보고서가 없습니다. 사전규격 상세에서 시작합니다.");
  await expect(entry.locator(".opportunity-deep-review-item")).toHaveCount(0);
});

test("두 지원 폭에서 가로로 넘치지 않고 상세 바닥 액션이 보인다", async ({ page }) => {
  await mockOpportunities(page);
  for (const viewport of [{ width: 1280, height: 800 }, { width: 1440, height: 900 }]) {
    await page.setViewportSize(viewport);
    await page.goto("/opportunities");
    await expect(page.locator(".opportunity-action-footer")).toBeVisible();
    const metrics = await page.evaluate(() => {
      const footer = document.querySelector(".opportunity-action-footer") as HTMLElement;
      const pane = document.querySelector(".review-split-list") as HTMLElement;
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

// 상세 머리는 공용 `StickyDecisionHeader`다(ADR-0062, 시안 M1c A안). 본문이 길어도
// 어느 발주기관의 어느 사업을 보고 있는지 화면에서 사라지지 않는다.
test("상세 본문을 끝까지 스크롤해도 상세 머리가 뷰포트 안에 남는다", async ({ page }) => {
  await mockOpportunities(page);
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.goto("/opportunities");

  const head = page.locator(".review-split-detail .review-detail-head");
  await expect(head).toBeVisible();
  await expect(head).toHaveAttribute("data-review-primitive", "sticky-decision-header");
  await expect(head).toContainText("발주기관");

  // 머리는 스크롤 통에 들어 있지 않다 — 본문이 움직여도 같은 자리에 남는다.
  const insideScroll = await head.evaluate((node) => Boolean(node.closest(".opportunity-detail-scroll")));
  expect(insideScroll, "상세 머리가 본문 스크롤 통 밖에 있다").toBe(false);

  const before = (await head.boundingBox())!;
  const scroller = page.locator(".opportunity-detail-scroll");
  const scrolled = await scroller.evaluate((node) => {
    node.scrollTop = node.scrollHeight;
    return node.scrollTop;
  });
  expect(scrolled, "상세 본문이 실제로 스크롤된다").toBeGreaterThan(0);

  const after = (await head.boundingBox())!;
  expect(after.y, "머리의 세로 위치가 스크롤로 바뀌지 않는다").toBeCloseTo(before.y, 0);
  expect(after.y, "머리가 뷰포트 위로 밀려나지 않는다").toBeGreaterThanOrEqual(0);
  expect(after.y + after.height, "머리가 뷰포트 안에 있다").toBeLessThanOrEqual(800);
});

// 목록 첫 줄은 공용 `--review-list-primary`(14.4px)를 읽는다 — 2026-09-21 M1c 승인:
// 네 목록의 첫 줄은 공용 값이다(명세 §2.4). 사업 추적만 갖고 있던 13.5px 단
// (`--opportunity-row-primary`)은 없앴고, 표 자체는 그대로 둔다(M1c A안). 둘째 줄
// (12.6px)은 바뀌지 않는다.
test("목록의 글자 크기가 물리 크기의 14.4px·12.6px 단을 지킨다", async ({ page }) => {
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
  expect(sizes.title).toBe("14.4px");
  expect(sizes.agency).toBe("14.4px");
  expect(sizes.meta).toBe("12.6px");
  expect(sizes.next).toBe("12.6px");
  expect(sizes.detailTitle).toBe("18px");
  expect(sizes.detailAgency).toBe("14.4px");
});
