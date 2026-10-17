import { expect, test, type Page } from "@playwright/test";
import { mockApi, mockOpportunityRecord, type OpportunityRecordMockTrace } from "./api-mock";
import { BID_DEADLINE, EXTERNAL_BID_URL, RECORD_NOW, TODAY_NOTE_AT } from "./fixtures/opportunity-record";

/*
 * RL-02 STEP-006 · spec T6 — `/opportunities/:id/*` 사업기회 레코드 화면.
 *
 * 고정 응답은 `mockApi`(미등록 경로는 404) 위에 건 `mockOpportunityRecord`이며 실제 백엔드에 연결하지
 * 않는다. 화면 시계는 `RECORD_NOW`(2026-10-16 금 10:30 KST)로 고정해 D-n·`오늘`이 결정적이다. 기대값은
 * 화면 코드를 가져오지 않고 fixture 값으로 직접 적었다. 레코드 id는 fixture 머리말을 본다.
 */

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const FULL_TITLE = "클라우드 기반 통합정보시스템 구축";

async function openRecord(page: Page, path: string): Promise<OpportunityRecordMockTrace> {
  await page.clock.setFixedTime(new Date(RECORD_NOW));
  await mockApi(page);
  const trace = await mockOpportunityRecord(page);
  await page.goto(path);
  return trace;
}

const pillTexts = (page: Page) => page.locator('[data-testid="record-header"] .rec-pill').allTextContents();
const crumbs = (page: Page) => page.locator("header.topbar .topbar-crumb");
const attribute = (page: Page, key: string) => page.locator(`.rec-attribute[data-attribute="${key}"]`);
const stage = (page: Page, label: string) => page.locator(`[data-testid="stage-bar"] .rec-stage[data-stage="${label}"]`);
const composerBody = (page: Page) => page.getByRole("textbox", { name: "노트 남기기" });
const actorInput = (page: Page) => page.getByLabel("담당자 이름", { exact: true });
const feedItems = (page: Page) => page.locator(".rec-activity");
const feedTitles = (page: Page) => page.locator(".rec-activity .rec-activity-title").allTextContents();
const toast = (page: Page) => page.locator(".toast");

test("/opportunities/:id는 활동 탭으로 replace 이동하고 알 수 없는 탭·식별자는 안전하게 처리한다", async ({ page }) => {
  await page.clock.setFixedTime(new Date(RECORD_NOW));
  await mockApi(page);
  await mockOpportunityRecord(page);

  await page.goto("/briefing");
  await page.goto("/opportunities/7101");
  await expect(page).toHaveURL(/\/opportunities\/7101\/activity$/);
  await expect(page.getByRole("tab", { name: "활동", exact: true })).toHaveAttribute("aria-selected", "true");
  // replace: 뒤로 가면 리다이렉트 출발 주소가 아니라 이전 화면이다.
  await page.goBack();
  await expect(page).toHaveURL(/\/briefing$/);

  await page.goto("/opportunities/7101/foo");
  await expect(page).toHaveURL(/\/opportunities\/7101\/activity$/);

  await page.goto("/opportunities/abc/activity");
  await expect(page.getByText("사업기회 식별자가 올바르지 않습니다")).toBeVisible();

  await page.goto("/opportunities/9999/activity");
  await expect(page.getByText("사업기회를 찾을 수 없습니다", { exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: "사업기회 목록 열기" })).toHaveAttribute("href", "/opportunities");
});

test("상단 경로는 사업기회 / 제목이고 제목이 오기 전에는 #id, 다른 레코드의 제목은 쓰지 않는다", async ({ page }) => {
  await page.clock.setFixedTime(new Date(RECORD_NOW));
  await mockApi(page);
  await mockOpportunityRecord(page);
  // 7101의 활동 응답만 붙잡아 제목이 오기 전 상태를 본다.
  let release: () => void = () => {};
  const gate = new Promise<void>((resolve) => { release = resolve; });
  await page.route(/\/api\/opportunities\/7101\/activity/, async (route) => {
    await gate;
    await route.fallback();
  });
  await page.goto("/opportunities/7101/activity");

  await expect(page.locator("header.topbar h1")).toHaveText("사업기회");
  await expect(page.locator("header.topbar")).toHaveAttribute("data-topbar-mode", "breadcrumb");
  await expect(crumbs(page)).toHaveText(["사업기회", "#7101"]);
  await expect(page.locator('[data-testid="record-title"]')).toHaveText("#7101");

  release();
  await expect(crumbs(page)).toHaveText(["사업기회", FULL_TITLE]);
  await expect(page.locator('[data-testid="record-title"]')).toHaveText(FULL_TITLE);
  await expect(page.locator("header.topbar").getByRole("link", { name: "사업기회", exact: true })).toHaveAttribute("href", "/opportunities");

  // 같은 앱 안에서 다른 레코드로 옮겨도 이전 제목이 경로에 남지 않는다(둘 다 새 레코드의 값이 오기 전에는 #id).
  await page.evaluate(() => {
    const seen: string[] = [];
    (window as unknown as { __crumbs: string[] }).__crumbs = seen;
    new MutationObserver(() => {
      seen.push(document.querySelector(".topbar-crumb.is-record")?.textContent ?? "");
    }).observe(document.querySelector("header.topbar")!, { subtree: true, childList: true, characterData: true });
    seen.push("NAV");
    window.history.pushState({}, "", "/opportunities/7102/activity");
    window.dispatchEvent(new PopStateEvent("popstate"));
  });
  await expect(crumbs(page)).toHaveText(["사업기회", "스마트 도시 통합플랫폼 고도화"]);
  const afterNav = await page.evaluate(() => (window as unknown as { __crumbs: string[] }).__crumbs);
  expect(afterNav.slice(afterNav.indexOf("NAV") + 1)).not.toContain(FULL_TITLE);
});

test("헤더 pill은 단계·마감·판정·추적 상태 순서이고 판정 보기·제안서 초안은 비활성이다", async ({ page }) => {
  await openRecord(page, "/opportunities/7101/activity");

  await expect(page.locator('[data-testid="record-title"]')).toHaveText(FULL_TITLE);
  expect(await pillTexts(page)).toEqual(["입찰공고", "D-4", "분석 대기", "계속 추적"]);
  await expect(page.locator('.rec-pill[data-pill="deadline"]')).toHaveClass(/is-warning/);

  const verdict = page.getByRole("button", { name: "판정 보기", exact: true });
  await expect(verdict).toBeDisabled();
  await expect(page.locator('.rec-action-hint[title="RL-03에서 열립니다"]')).toHaveCount(1);
  await expect(page.getByRole("button", { name: "제안서 초안", exact: true })).toBeDisabled();
  await expect(page.getByRole("button", { name: "사업기회 더보기" })).toBeVisible();

  // 같은 규칙의 다른 조합.
  for (const [path, expected] of [
    ["/opportunities/7102/activity", ["발주계획", "연차 추적", "미선택"]],
    ["/opportunities/7103/activity", ["사전규격", "의견 마감 D-2", "분석 대기", "미선택"]],
    ["/opportunities/7104/activity", ["입찰공고", "마감 지남", "분석 대기", "보류"]],
    ["/opportunities/7105/activity", ["단계 미확인", "분석 대기", "미선택"]],
  ] as const) {
    await page.goto(path);
    await expect(page.locator('[data-testid="record-header"] .rec-pill[data-pill="stage"]')).toBeVisible();
    await expect.poll(() => pillTexts(page), path).toEqual(expected);
  }
});

test("같은 단계에 권위 연결이 둘이면 서버가 준 대표(stages[].link_id)로 헤더·속성·공고·비슷한 공고를 읽는다", async ({ page }) => {
  // 7109: 옛 입찰공고 A(연결 7061·공고 9601, 마감 10/9 지남)가 연결 목록 앞에 있고, 새 입찰공고
  // B(연결 7062·공고 9602, 마감 10/21 = D-5)가 서버 대표다. 화면은 대표를 스스로 고르지 않는다.
  const trace = await openRecord(page, "/opportunities/7109/activity");

  await expect(page.locator('[data-testid="record-title"]')).toHaveText("통합 민원 포털 재구축 (재공고)");
  await expect.poll(() => pillTexts(page)).toEqual(["입찰공고", "D-5", "분석 대기", "미선택"]);
  await expect(page.locator('.rec-pill[data-pill="deadline"]')).not.toHaveText("마감 지남");
  await expect(attribute(page, "bid_deadline").locator("dd")).toHaveText("10월 21일 (수) 18:00");
  await expect(attribute(page, "amount").locator("dd")).toHaveText("2억 5,400만원 · 추정가격");
  await expect(attribute(page, "method").locator("dd")).toHaveText("협상에 의한 계약");
  await expect(attribute(page, "joint").locator("dd")).toHaveText("분담이행방식");
  expect(trace.noticeGets).not.toContain(9601);
  expect(trace.noticeGets).toContain(9602);

  await page.getByRole("tab", { name: "비슷한 공고", exact: true }).click();
  const list = page.getByRole("list", { name: "비슷한 공고" });
  await expect(list.getByRole("link", { name: "통합 민원 포털 재구축", exact: true })).toHaveAttribute("href", "/judgments/9601");
  expect(trace.relatedGets).toEqual([9602]);
});

test("속성 8개는 고정 순서이고 값이 없으면 미공개·미지정이다", async ({ page }) => {
  await openRecord(page, "/opportunities/7101/activity");
  await expect(page.locator(".rec-attribute dt")).toHaveText(["발주기관", "사업기간", "금액", "계약방법", "공동수급", "입찰 마감", "담당", "추적"]);
  await expect(attribute(page, "agency").locator("dd")).toHaveText("해솔시청");
  await expect(attribute(page, "period").locator("dd")).toHaveText("미공개");
  await expect(attribute(page, "amount").locator("dd")).toHaveText("12억 3,000만원 · 추정가격");
  await expect(attribute(page, "method").locator("dd")).toHaveText("제한경쟁입찰");
  await expect(attribute(page, "joint").locator("dd")).toHaveText("공동이행방식");
  await expect(attribute(page, "bid_deadline").locator("dd")).toHaveText("10월 20일 (화) 18:00");
  // 담당 = 마지막 반응·결정의 기록자. 결정(10/15 14:05)이 반응(10/15 09:10)보다 늦다.
  await expect(attribute(page, "owner").locator("dd")).toHaveText("최담당");
  await expect(attribute(page, "tracking").locator("dd")).toHaveText("계속 추적 · 최담당");
  await expect(attribute(page, "period").locator("dd")).toHaveClass(/is-empty/);

  // 발주계획만: 금액은 예산, 사업기간은 발주 예정월, 그 밖은 미공개·미지정.
  await page.goto("/opportunities/7102/activity");
  await expect(attribute(page, "agency").locator("dd")).toHaveText("바다시청");
  await expect(attribute(page, "period").locator("dd")).toHaveText("3월 발주 예정");
  await expect(attribute(page, "amount").locator("dd")).toHaveText("4억 5,000만원 · 예산");
  await expect(attribute(page, "method").locator("dd")).toHaveText("미공개");
  await expect(attribute(page, "joint").locator("dd")).toHaveText("미공개");
  await expect(attribute(page, "bid_deadline").locator("dd")).toHaveText("미공개");
  await expect(attribute(page, "owner").locator("dd")).toHaveText("미지정");
  await expect(attribute(page, "tracking").locator("dd")).toHaveText("미선택");

  // 사전규격만: 추정가격이 없으면 예산, 입찰 마감은 미공개(의견 마감은 헤더 pill에만).
  await page.goto("/opportunities/7103/activity");
  await expect(attribute(page, "amount").locator("dd")).toHaveText("8억원 · 예산");
  await expect(attribute(page, "bid_deadline").locator("dd")).toHaveText("미공개");
  await expect(attribute(page, "method").locator("dd")).toHaveText("미공개");

  // 연결이 없으면 값을 만들지 않는다.
  await page.goto("/opportunities/7105/activity");
  await expect(attribute(page, "agency").locator("dd")).toHaveText("미공개");
  await expect(attribute(page, "amount").locator("dd")).toHaveText("미공개");
  await expect(attribute(page, "tracking").locator("dd")).toHaveText("미선택");

  // 억 미만 금액도 반올림하지 않는다.
  await page.goto("/opportunities/7108/activity");
  await expect(attribute(page, "amount").locator("dd")).toHaveText("5만원 · 추정가격");
});

test("제출 서류 블록은 비활성 안내 한 줄뿐이고 진행 막대·숫자가 없다", async ({ page }) => {
  await openRecord(page, "/opportunities/7101/activity");
  const block = page.getByRole("region", { name: "제출 서류" });
  await expect(block.locator("p")).toHaveText("제출 서류 체크는 준비 중입니다");
  await expect(block.locator("p")).toHaveAttribute("aria-disabled", "true");
  await expect(block.locator('[role="progressbar"], progress')).toHaveCount(0);
  await expect(block).not.toContainText("/ 27");
});

test("단계 바는 서버 상태 6개를 그대로 그리고 unknown은 미확인 글자와 회색 테두리다", async ({ page }) => {
  await openRecord(page, "/opportunities/7101/activity");
  await expect(stage(page, "발주계획")).toBeVisible();
  const states = await page.locator('[data-testid="stage-bar"] .rec-stage').evaluateAll((nodes) => nodes.map((node) => [node.getAttribute("data-stage"), node.getAttribute("data-state")]));
  expect(states).toEqual([
    ["발주계획", "done"], ["사전규격", "done"], ["입찰공고", "current"],
    ["마감", "upcoming_deadline"], ["개찰", "unknown"], ["계약", "unknown"],
  ]);
  // 상태는 색만으로 말하지 않는다: 미확인은 글자, 나머지는 숨은 상태 이름이 붙는다.
  await expect(stage(page, "개찰")).toContainText("미확인");
  await expect(stage(page, "발주계획")).toContainText("완료");
  await expect(stage(page, "마감")).toContainText("10월 20일");
  // 완료 단계는 ✓ 아이콘, 그 밖은 비어 있다.
  await expect(stage(page, "발주계획").locator("svg")).toHaveCount(1);
  await expect(stage(page, "개찰").locator("svg")).toHaveCount(0);

  await page.goto("/opportunities/7102/activity");
  const border = (label: string) => stage(page, label).locator(".rec-stage-marker").evaluate((node) => getComputedStyle(node).borderTopColor);
  const doneBorder = await border("발주계획");
  const pendingBorder = await border("사전규격");
  const unknownBorder = await border("마감");
  // 대기와 미확인은 같은 회색 테두리이고 현재(채움 색)와 다르다.
  expect(unknownBorder).toBe(pendingBorder);
  expect(unknownBorder).not.toBe(doneBorder);
  await expect(stage(page, "발주계획")).toHaveAttribute("data-state", "current");
  await expect(stage(page, "사전규격")).toHaveAttribute("data-state", "pending");
  await expect(stage(page, "사전규격")).not.toContainText("미확인");
  await expect(stage(page, "마감")).toContainText("미확인");
});

test("활동 항목은 분 단위 시각·사람 이름·상태 pill·링크를 그리고 초 단위와 시스템 정보를 노출하지 않는다", async ({ page }) => {
  await openRecord(page, "/opportunities/7101/activity");
  await expect(feedItems(page)).toHaveCount(11);

  const first = feedItems(page).first();
  await expect(first).toHaveAttribute("data-kind", "note_added");
  await expect(first.locator("strong")).toHaveText("홍길동");
  await expect(first.locator(".rec-activity-title")).toHaveText("홍길동 공급사 의견을 주 후반에 정리");
  await expect(first.locator(".rec-activity-meta")).toHaveText("오늘 08:41");
  // 초 단위(08:41:27)는 화면에 없다.
  expect(TODAY_NOTE_AT).toContain(":27");
  await expect(page.locator(".rec-main")).not.toContainText("08:41:27");
  await expect(page.locator(".rec-main")).not.toContainText(":27");
  // 기계 판독 속성(`<time dateTime>`)도 분 단위까지만 싣는다(초·마이크로초 없음).
  await expect(first.locator("time")).toHaveAttribute("datetime", "2026-10-16T08:41+09:00");
  const dateTimes = await page.locator(".rec-activity time").evaluateAll((nodes) => nodes.map((node) => node.getAttribute("datetime")));
  expect(dateTimes).toHaveLength(11);
  for (const value of dateTimes) expect(value).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}\+09:00$/);

  const reacted = page.locator('.rec-activity[data-kind="briefing_reacted"]');
  await expect(reacted.locator(".rec-activity-pill")).toHaveText("채택");
  await expect(reacted.locator(".rec-activity-meta")).toHaveText("10월 15일 · 브리핑에서 보기");
  await expect(reacted.getByRole("link", { name: "브리핑에서 보기" })).toHaveAttribute("href", /^\/briefing\?date=2026-10-15&selected=/);

  // 공고 외부 URL은 새 창으로, 내부 경로는 앱 링크로 연다.
  const bid = page.locator('.rec-activity[data-kind="bid_posted"]');
  const bidLink = bid.getByRole("link", { name: "공고 보기" });
  await expect(bidLink).toHaveAttribute("href", EXTERNAL_BID_URL);
  await expect(bidLink).toHaveAttribute("target", "_blank");
  await expect(bidLink).toHaveAttribute("rel", /noopener/);
  await expect(page.locator('.rec-activity[data-kind="pre_spec_opened"]').getByRole("link", { name: "사전규격 보기" })).toHaveAttribute("href", "/pre-specs/9102");

  // 사람 항목은 머리글자 아바타, 사업 사건은 아이콘이다.
  await expect(first.locator(".rec-activity-mark")).toHaveClass(/is-person/);
  await expect(first.locator(".rec-activity-mark")).toHaveText("홍");
  await expect(bid.locator(".rec-activity-mark")).not.toHaveClass(/is-person/);
  await expect(bid.locator(".rec-activity-mark svg")).toHaveCount(1);

  // 최신순(내림)이고 시스템 처리(회차·변환·호출·정책) 항목이 없다.
  const kinds = await feedItems(page).evaluateAll((nodes) => nodes.map((node) => node.getAttribute("data-kind")));
  expect(kinds).toEqual([
    "note_added", "action_added", "action_done", "action_added", "tracking_decided", "briefing_reacted",
    "recheck_signal", "notice_corrected", "bid_posted", "pre_spec_opened", "order_plan_found",
  ]);
});

test("필터 칩은 받아 둔 항목을 클라이언트에서 가르고 서버를 다시 부르지 않는다", async ({ page }) => {
  const trace = await openRecord(page, "/opportunities/7101/activity");
  await expect(feedItems(page)).toHaveCount(11);
  const requests = trace.activityGets.length;

  const chips = page.getByRole("group", { name: "활동 필터" });
  await expect(chips.getByRole("button")).toHaveText(["전체", "사람", "사업 사건"]);
  await expect(chips.getByRole("button", { name: "전체" })).toHaveAttribute("aria-pressed", "true");

  await chips.getByRole("button", { name: "사람" }).click();
  await expect(chips.getByRole("button", { name: "사람" })).toHaveAttribute("aria-pressed", "true");
  expect(await feedItems(page).evaluateAll((nodes) => nodes.map((node) => node.getAttribute("data-kind")))).toEqual([
    "note_added", "action_added", "action_done", "action_added", "tracking_decided", "briefing_reacted",
  ]);

  await chips.getByRole("button", { name: "사업 사건" }).click();
  // 기록자가 없는 재확인 신호는 사업 사건이다.
  expect(await feedItems(page).evaluateAll((nodes) => nodes.map((node) => node.getAttribute("data-kind")))).toEqual([
    "recheck_signal", "notice_corrected", "bid_posted", "pre_spec_opened", "order_plan_found",
  ]);

  await chips.getByRole("button", { name: "전체" }).click();
  await expect(feedItems(page)).toHaveCount(11);
  expect(trace.activityGets.length).toBe(requests);
});

test("활동이 없으면 빈 상태를 말하고, 더 보기는 서버 커서로 다음 페이지를 이어 붙인다", async ({ page }) => {
  const trace = await openRecord(page, "/opportunities/7102/activity");
  await expect(feedItems(page)).toHaveCount(1);
  await expect(page.getByRole("button", { name: "더 보기" })).toHaveCount(0);

  await page.goto("/opportunities/7105/activity");
  await expect(page.getByText("아직 기록된 활동이 없습니다")).toBeVisible();

  await page.goto("/opportunities/7108/activity");
  await expect(feedItems(page)).toHaveCount(50);
  const more = page.getByRole("button", { name: "더 보기" });
  await expect(more).toBeVisible();
  const lastShown = await feedItems(page).last().getAttribute("data-item-id");
  await more.click();
  await expect(feedItems(page)).toHaveCount(60);
  await expect(page.getByRole("button", { name: "더 보기" })).toHaveCount(0);

  const paged = trace.activityGets.find((params) => params.has("before") && !params.has("kinds"));
  expect(paged?.get("before")).toMatch(new RegExp(`\\|${lastShown}$`));
  expect(paged?.get("limit")).toBe("50");
  // 같은 항목이 두 번 그려지지 않는다.
  const ids = await feedItems(page).evaluateAll((nodes) => nodes.map((node) => node.getAttribute("data-item-id")));
  expect(new Set(ids).size).toBe(60);
});

test("노트는 담당자 이름 없이 저장되지 않고, ⌘Enter로 저장하며 UUID 요청 식별자와 기록자 헤더가 나간다", async ({ page }) => {
  const trace = await openRecord(page, "/opportunities/7101/activity");
  await expect(feedItems(page)).toHaveCount(11);

  await composerBody(page).fill("공급사 의견을 정리해서 공유");
  await page.getByRole("button", { name: "노트", exact: true }).click();
  // 이름이 없으면 저장하지 않고 이유를 말한다.
  await expect(page.locator(".rec-composer")).toContainText("담당자 이름을 입력한 뒤 저장하세요");
  expect(trace.noteCreates).toHaveLength(0);
  await expect(composerBody(page)).toHaveValue("공급사 의견을 정리해서 공유");
  await expect(actorInput(page)).toBeFocused();

  await actorInput(page).fill("김담당");
  await composerBody(page).focus();
  await page.keyboard.press("Meta+Enter");

  await expect(feedItems(page).first().locator("strong")).toHaveText("김담당");
  await expect(feedItems(page).first().locator(".rec-activity-title")).toHaveText("김담당 공급사 의견을 정리해서 공유");
  await expect(feedItems(page).first().locator(".rec-activity-meta")).toHaveText(/^오늘 10:3\d$/);
  await expect(composerBody(page)).toHaveValue("");
  await expect(toast(page)).toContainText("노트를 남겼습니다");
  expect(trace.noteCreates).toHaveLength(1);
  expect(trace.noteCreates[0].body).toEqual({ kind: "note", body: "공급사 의견을 정리해서 공유", request_id: expect.stringMatching(UUID) });
  // 헤더는 비ASCII 이름의 percent 인코딩 계약을 따른다(감사 표식이며 인증이 아니다).
  expect(trace.noteCreates[0].headers["x-bidops-actor-name-format"]).toBe("utf-8-percent-v1");
  expect(decodeURIComponent(trace.noteCreates[0].headers["x-bidops-actor-name"].replace("UTF-8''", ""))).toBe("김담당");
});

test("다음 행동은 담당을 선택 입력으로 보내고 좌측 목록에 체크 항목으로 나타난다", async ({ page }) => {
  const trace = await openRecord(page, "/opportunities/7101/activity");
  await actorInput(page).fill("김담당");

  await composerBody(page).fill("현장 설명회 참석 신청");
  await page.getByLabel("담당", { exact: true }).fill("박팀장");
  await page.getByRole("button", { name: "다음 행동", exact: true }).click();

  expect(trace.noteCreates).toHaveLength(1);
  expect(trace.noteCreates[0].body).toEqual({ kind: "action", body: "현장 설명회 참석 신청", owner: "박팀장", request_id: expect.stringMatching(UUID) });
  await expect(toast(page)).toContainText("다음 행동을 남겼습니다");
  await expect(page.getByLabel("담당", { exact: true })).toHaveValue("");

  const next = page.getByTestId("next-actions");
  await expect(next.getByRole("checkbox")).toHaveCount(2);
  await expect(next.getByRole("checkbox", { name: "현장 설명회 참석 신청" })).not.toBeChecked();
  await expect(next.getByRole("checkbox", { name: "입찰 참여 조건 확인" })).not.toBeChecked();
  // 완료된 항목("제안서 목차 초안")은 목록에 없다.
  await expect(next).not.toContainText("제안서 목차 초안");
  // 머리글자는 기록자가 아니라 담당 이름이다(detail "담당 <이름>", 결정 #14).
  const items = next.locator(".rec-next-item");
  await expect(items.filter({ hasText: "현장 설명회 참석 신청" }).locator(".rec-avatar")).toHaveAttribute("title", "담당 박팀장");
  await expect(items.filter({ hasText: "입찰 참여 조건 확인" }).locator(".rec-avatar")).toHaveAttribute("title", "담당 김실무");
  await expect(feedItems(page).first()).toHaveAttribute("data-kind", "action_added");
  await expect(feedItems(page).first().locator(".rec-activity-title")).toContainText("다음 행동: 현장 설명회 참석 신청");
});

test("저장이 실패하면 입력을 그대로 두고, 같은 입력의 재시도는 같은 요청 식별자를 쓰며 바꾸면 새 식별자다", async ({ page }) => {
  const trace = await openRecord(page, "/opportunities/7101/activity");
  await actorInput(page).fill("김담당");
  await composerBody(page).fill("서버가 잠깐 못 받는 노트");

  trace.failNotes({ status: 503, code: "service_unavailable" });
  await page.getByRole("button", { name: "노트", exact: true }).click();
  await expect(page.locator(".rec-composer").getByRole("alert")).toContainText("저장되지 않았습니다");
  await expect(composerBody(page)).toHaveValue("서버가 잠깐 못 받는 노트");
  await expect(feedItems(page)).toHaveCount(11);

  trace.failNotes(null);
  await page.getByRole("button", { name: "노트", exact: true }).click();
  await expect(feedItems(page)).toHaveCount(12);
  await expect(page.locator(".rec-composer").getByRole("alert")).toHaveCount(0);
  expect(trace.noteCreates).toHaveLength(2);
  expect(trace.noteCreates[1].body.request_id).toBe(trace.noteCreates[0].body.request_id);

  // 새 입력은 새 식별자.
  await composerBody(page).fill("다음 노트");
  await page.getByRole("button", { name: "노트", exact: true }).click();
  await expect(feedItems(page)).toHaveCount(13);
  expect(trace.noteCreates[2].body.request_id).not.toBe(trace.noteCreates[1].body.request_id);

  // 안전한 오류 코드는 사람 문구로 옮긴다.
  trace.failNotes({ status: 409, code: "idempotency_conflict" });
  await composerBody(page).fill("충돌 노트");
  await page.getByRole("button", { name: "노트", exact: true }).click();
  await expect(page.locator(".rec-composer").getByRole("alert")).toContainText("같은 요청 식별자가 다른 요청에 이미 쓰였습니다");
});

test("저장 중 같은 입력을 연달아 눌러도 한 번만 보낸다", async ({ page }) => {
  const trace = await openRecord(page, "/opportunities/7101/activity");
  await actorInput(page).fill("김담당");
  await composerBody(page).fill("중복 제출 확인");
  const hold = trace.holdNotes();
  await composerBody(page).focus();
  await page.keyboard.press("Control+Enter");
  await expect.poll(() => trace.noteCreates.length).toBe(1);
  await page.keyboard.press("Control+Enter");
  hold.release();
  await expect(feedItems(page)).toHaveCount(12);
  expect(trace.noteCreates).toHaveLength(1);
});

test("저장하지 않은 노트 초안은 beforeunload와 SPA 이동을 지키고, 탭을 오가도 초안이 남는다", async ({ page }) => {
  await openRecord(page, "/opportunities/7101/activity");
  await composerBody(page).fill("아직 저장하지 않은 노트");
  expect(await page.evaluate(() => {
    const event = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(event);
    return event.defaultPrevented;
  })).toBe(true);

  // 다른 탭으로 가는 이동도 확인을 거친다. 계속 편집하면 같은 탭에 초안이 그대로 있다.
  await page.getByRole("tab", { name: "판정", exact: true }).click();
  const guard = page.getByRole("alertdialog");
  await expect(guard).toBeVisible();
  await expect(guard).toContainText("사업기회 레코드를 떠납니다");
  await guard.getByRole("button", { name: "계속 편집", exact: true }).click();
  await expect(page).toHaveURL(/\/opportunities\/7101\/activity$/);
  await expect(composerBody(page)).toHaveValue("아직 저장하지 않은 노트");

  // 지우면 보호도 풀린다.
  await composerBody(page).fill("");
  expect(await page.evaluate(() => {
    const event = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(event);
    return event.defaultPrevented;
  })).toBe(false);
  await page.getByRole("tab", { name: "판정", exact: true }).click();
  await expect(page).toHaveURL(/\/opportunities\/7101\/verdict$/);
});

test("다음 행동 체크는 완료를 저장하고 이름이 없으면 저장하지 않으며 note_not_action을 사람 문구로 말한다", async ({ page }) => {
  const trace = await openRecord(page, "/opportunities/7101/activity");
  const next = page.getByTestId("next-actions");
  const open = next.getByRole("checkbox", { name: "입찰 참여 조건 확인" });

  await open.click();
  await expect(toast(page)).toContainText("담당자 이름을 먼저 입력하세요");
  await expect(open).not.toBeChecked();
  expect(trace.noteDones).toHaveLength(0);
  await expect(actorInput(page)).toBeFocused();

  const donePath = /\/api\/opportunities\/7101\/notes\/[^/]+\/done$/;
  await page.route(donePath, async (route) => {
    await route.fulfill({ status: 409, contentType: "application/json", body: JSON.stringify({ error: { code: "note_not_action", message: "x", details: null }, request_id: null }) });
  });
  await actorInput(page).fill("김담당");
  await open.click();
  await expect(toast(page)).toContainText("다음 행동만 완료로 표시할 수 있습니다");
  // 저장에 실패하면 체크가 풀리고 항목은 목록에 남는다(완료로 확정하지 않는다).
  await expect(open).not.toBeChecked();
  await page.unroute(donePath);

  await open.click();
  // 앞의 두 번은 서버(mock)에 닿지 않았다: 이름이 없어 보내지 않았고, 둘째는 위 409가 가로챘다.
  await expect.poll(() => trace.noteDones.length).toBe(1);
  expect(trace.noteDones[0].body).toEqual({ request_id: expect.stringMatching(UUID) });
  expect(decodeURIComponent(trace.noteDones[0].headers["x-bidops-actor-name"].replace("UTF-8''", ""))).toBe("김담당");
  await expect(next.getByRole("checkbox", { name: "입찰 참여 조건 확인" })).toHaveCount(0);
  await expect(next).toContainText("남은 다음 행동이 없습니다");
  await expect(feedItems(page).first().locator(".rec-activity-title")).toHaveText("김담당이 완료: 입찰 참여 조건 확인");
});

test("다음 행동은 최대 5건만 보이고 모두 보기가 피드를 다음 행동으로 거른다", async ({ page }) => {
  await openRecord(page, "/opportunities/7101/activity");
  await actorInput(page).fill("김담당");
  for (const text of ["행동 A", "행동 B", "행동 C", "행동 D", "행동 E", "행동 F"]) {
    await composerBody(page).fill(text);
    await page.getByRole("button", { name: "다음 행동", exact: true }).click();
    await expect(composerBody(page)).toHaveValue("");
  }
  const next = page.getByTestId("next-actions");
  // 열린 행동 7건(기존 1 + 6) 중 5건.
  await expect(next.getByRole("checkbox")).toHaveCount(5);
  await expect(next).toContainText("남은 다음 행동 7건 중 5건을 보여 줍니다");

  await next.getByRole("button", { name: "모두 보기" }).click();
  const chips = page.getByRole("group", { name: "활동 필터" });
  await expect(chips.getByRole("button")).toHaveText(["전체", "사람", "사업 사건", "다음 행동"]);
  await expect(chips.getByRole("button", { name: "다음 행동" })).toHaveAttribute("aria-pressed", "true");
  const kinds = await feedItems(page).evaluateAll((nodes) => nodes.map((node) => node.getAttribute("data-kind")));
  expect(kinds.length).toBe(9);
  expect(new Set(kinds)).toEqual(new Set(["action_added", "action_done"]));
  // 다른 칩을 누르면 임시 칩이 사라진다.
  await chips.getByRole("button", { name: "전체" }).click();
  await expect(chips.getByRole("button")).toHaveText(["전체", "사람", "사업 사건"]);
});

test("판정·제안서·서류 탭은 빈 상태 문장만 그리고 좌측 정보는 탭을 옮겨도 남는다", async ({ page }) => {
  await openRecord(page, "/opportunities/7101/activity");
  for (const [tab, sentence] of [
    ["판정", "판정은 분석이 끝나면 여기에 보입니다"],
    ["제안서", "제안서 초안은 판정 뒤 만들 수 있습니다"],
    ["서류", "제출 서류 체크는 준비 중입니다"],
  ] as const) {
    await page.getByRole("tab", { name: tab, exact: true }).click();
    await expect(page.getByRole("tab", { name: tab, exact: true })).toHaveAttribute("aria-selected", "true");
    await expect(page.getByRole("tabpanel")).toContainText(sentence);
    await expect(page.locator(".rec-stagebar")).toHaveCount(0);
    await expect(page.locator(".rec-attribute")).toHaveCount(8);
  }
  await expect(page).toHaveURL(/\/opportunities\/7101\/documents$/);
});

test("원문 탭은 공고 상세로 가는 링크를 주고 비슷한 공고는 가장 뒤 단계 공고의 관련 목록을 쓴다", async ({ page }) => {
  const trace = await openRecord(page, "/opportunities/7101/source");
  await expect(page.getByRole("tabpanel")).toContainText("원문은 공고 상세에서 봅니다");
  await expect(page.getByRole("tabpanel").getByRole("link", { name: /공고 판정 이력 열기/ })).toHaveAttribute("href", "/judgments/9103");
  await expect(page.getByRole("tabpanel").getByRole("link", { name: /나라장터 공고 원문 열기/ })).toHaveAttribute("href", EXTERNAL_BID_URL);

  await page.getByRole("tab", { name: "비슷한 공고", exact: true }).click();
  const list = page.getByRole("list", { name: "비슷한 공고" });
  await expect(list.getByRole("listitem")).toHaveCount(2);
  await expect(list.getByRole("link", { name: "클라우드 기반 통합정보시스템 구축 (재공고)" })).toHaveAttribute("href", "/judgments/9111");
  await expect(list).toContainText("정정 사유: 마감일 연장");
  expect(trace.relatedGets).toEqual([9103]);

  // 발주계획만 있으면 공고가 없어 관련 목록을 묻지 않고 빈 상태를 말한다.
  await page.goto("/opportunities/7102/similar");
  await expect(page.getByRole("tabpanel")).toContainText("공고가 연결되면 비슷한 공고를 찾습니다");
  expect(trace.relatedGets).toEqual([9103]);
  await page.goto("/opportunities/7102/source");
  await expect(page.getByRole("tabpanel").getByRole("link", { name: /발주계획 검토목록 열기/ })).toHaveAttribute("href", "/order-plans?selected=7011");
});

test("탭은 ←→ 키로 옮기고 선택이 주소에 남는다", async ({ page }) => {
  await openRecord(page, "/opportunities/7101/activity");
  await expect(page.getByRole("tab")).toHaveCount(6);
  const names = await page.getByRole("tab").evaluateAll((nodes) => nodes.map((node) => (node.querySelector("span span")?.textContent ?? node.textContent ?? "").trim()));
  expect(names).toEqual(["활동", "판정", "제안서", "서류", "원문", "비슷한 공고"]);
  await page.getByRole("tab", { name: "활동", exact: true }).focus();
  await page.keyboard.press("ArrowRight");
  await expect(page).toHaveURL(/\/opportunities\/7101\/verdict$/);
  await expect(page.getByRole("tab", { name: "판정", exact: true })).toHaveAttribute("aria-selected", "true");
  await expect(page.getByRole("tab", { name: "판정", exact: true })).toBeFocused();
  await page.keyboard.press("ArrowRight");
  await expect(page).toHaveURL(/\/opportunities\/7101\/proposal$/);
  await page.keyboard.press("ArrowLeft");
  await page.keyboard.press("ArrowLeft");
  await expect(page).toHaveURL(/\/opportunities\/7101\/activity$/);
  await expect(page.getByRole("tab", { name: "활동", exact: true })).toBeFocused();
});

test("병합된 사업기회는 병합 대상 레코드로 이동한다", async ({ page }) => {
  await openRecord(page, "/opportunities/7106/similar");
  await expect(page).toHaveURL(/\/opportunities\/7101\/similar$/);
  await expect(page.locator('[data-testid="record-title"]')).toHaveText(FULL_TITLE);
  await expect(crumbs(page)).toHaveText(["사업기회", FULL_TITLE]);
});

test("⋯ 메뉴는 기존 추적 대화상자를 열고 저장하면 헤더·속성·활동이 다시 읽힌다", async ({ page }) => {
  const trace = await openRecord(page, "/opportunities/7101/activity");
  await page.getByRole("button", { name: "사업기회 더보기" }).click();
  const menu = page.getByRole("menu");
  await expect(menu.getByRole("menuitem")).toHaveText([/추적 상태 변경/, /추적 되돌리기/, /신호 확인/, /후보 연결/]);
  await expect(menu.getByRole("menuitem", { name: /신호 확인/ })).toBeDisabled();
  await expect(menu.getByRole("menuitem", { name: /후보 연결/ })).toBeDisabled();
  await expect(menu.getByRole("menuitem", { name: /추적 되돌리기/ })).toBeEnabled();
  await menu.getByRole("menuitem", { name: /추적 상태 변경/ }).click();

  const dialog = page.getByRole("dialog");
  await expect(dialog.getByRole("heading", { name: "추적 상태 변경" })).toBeVisible();
  await dialog.getByRole("combobox", { name: "추적 상태", exact: true }).click();
  await page.getByRole("option", { name: "보류", exact: true }).click();
  await dialog.getByRole("combobox", { name: "선택 사유", exact: true }).click();
  await page.getByRole("option", { name: "예산·일정 추가 확인 필요", exact: true }).click();
  await dialog.getByLabel("결정 기록자", { exact: true }).fill("김담당");
  await dialog.getByRole("button", { name: "변경 사항 적용", exact: true }).click();

  await expect(page.getByRole("dialog")).toHaveCount(0);
  expect(trace.trackingPatches).toHaveLength(1);
  expect(trace.trackingPatches[0].body).toEqual({ tracking_status: "보류", reason: "예산·일정 추가 확인 필요" });
  expect(await pillTexts(page)).toEqual(["입찰공고", "D-4", "분석 대기", "보류"]);
  await expect(attribute(page, "tracking").locator("dd")).toHaveText("보류 · 김담당");
  await expect(feedItems(page).first().locator(".rec-activity-title")).toHaveText("김담당이 보류으로 결정");
});

test("⋯ 메뉴의 추적 되돌리기와 후보 연결은 기존 대화상자를 열고 해당이 없으면 이유와 함께 비활성이다", async ({ page }) => {
  await openRecord(page, "/opportunities/7101/activity");
  await page.getByRole("button", { name: "사업기회 더보기" }).click();
  await page.getByRole("menuitem", { name: /추적 되돌리기/ }).click();
  const reset = page.getByRole("dialog");
  await expect(reset.getByRole("heading", { name: "추적 되돌리기" })).toBeVisible();
  await expect(reset.getByRole("button", { name: "미선택으로 되돌리기" })).toBeEnabled();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);

  // 미선택이면 되돌릴 결정이 없다.
  await page.goto("/opportunities/7102/activity");
  await page.getByRole("button", { name: "사업기회 더보기" }).click();
  await expect(page.getByRole("menuitem", { name: /추적 되돌리기/ })).toBeDisabled();
  await expect(page.getByRole("menu")).toContainText("이미 미선택입니다");
  await page.keyboard.press("Escape");

  // 확인할 후보가 있으면 후보 연결 확인 대화상자가 열린다.
  await page.goto("/opportunities/7105/activity");
  await page.getByRole("button", { name: "사업기회 더보기" }).click();
  await page.getByRole("menuitem", { name: /후보 연결/ }).click();
  await expect(page.getByRole("dialog").getByRole("heading", { name: "사전규격 후보 연결 확인" })).toBeVisible();
});

test("레코드 DOM에 회차·정책·모델·참조 실행 표식이 없다", async ({ page }) => {
  await openRecord(page, "/opportunities/7101/activity");
  const forbidden = /run_id|unmeasured_reference|mock_reference|policy_id|policy_sha|c2-order-plan|qwen|gpt-\d|luna|\d{8}-\d{8}--/i;
  for (const tab of ["activity", "verdict", "proposal", "documents", "source", "similar"]) {
    await page.goto(`/opportunities/7101/${tab}`);
    await expect(page.locator(".rec-body")).toBeVisible();
    await expect(page.locator('[data-testid="record-title"]')).toHaveText(FULL_TITLE);
    const html = await page.locator(".page-canvas").evaluate((node) => node.innerHTML);
    expect(html, `${tab} 탭`).not.toMatch(forbidden);
    const text = await page.locator("header.topbar").innerText();
    expect(text).not.toMatch(forbidden);
  }
  expect(BID_DEADLINE).toContain("2026-10-20");
});

for (const viewport of [{ width: 1280, height: 800 }, { width: 1440, height: 900 }]) {
  test(`${viewport.width}px에서 가로로 넘치지 않고 좌측 정보가 280px이며 작성기가 보인다`, async ({ page }) => {
    await page.setViewportSize(viewport);
    await openRecord(page, "/opportunities/7101/activity");
    await expect(feedItems(page)).toHaveCount(11);
    const metrics = await page.evaluate(() => {
      const canvas = document.querySelector(".page-canvas") as HTMLElement;
      const side = document.querySelector(".rec-side") as HTMLElement;
      const header = document.querySelector(".rec-header") as HTMLElement;
      const actions = document.querySelector(".rec-actions") as HTMLElement;
      return {
        pageOverflow: document.documentElement.scrollWidth - window.innerWidth,
        canvasOverflow: canvas.scrollWidth - canvas.clientWidth,
        side: side.getBoundingClientRect().width,
        actionsRight: actions.getBoundingClientRect().right,
        headerRight: header.getBoundingClientRect().right,
        actionsTop: actions.getBoundingClientRect().top,
        headerTop: header.getBoundingClientRect().top,
        headerBottom: header.getBoundingClientRect().bottom,
      };
    });
    expect(metrics.pageOverflow).toBeLessThanOrEqual(0);
    expect(metrics.canvasOverflow).toBeLessThanOrEqual(0);
    expect(Math.round(metrics.side)).toBe(280);
    expect(metrics.actionsRight).toBeLessThanOrEqual(metrics.headerRight + 1);
    expect(metrics.actionsTop).toBeGreaterThanOrEqual(metrics.headerTop);
    expect(metrics.actionsTop).toBeLessThan(metrics.headerBottom);
    await expect(composerBody(page)).toBeVisible();
    await expect(page.getByRole("button", { name: "노트", exact: true })).toBeVisible();
  });
}
