import { expect, test, type Page } from "@playwright/test";
import { mockApi, mockBriefing, type BriefingMockOptions } from "./api-mock";
import {
  BRIEFING_DATE,
  BRIEFING_MONDAY_DATE,
  BRIEFING_NOW,
  BRIEFING_PREVIOUS_DATE,
  LONG_TITLE,
  briefingFixture,
  briefingItemId,
  emptyBriefingFixture,
  incompleteBriefingFixture,
  mondayBriefingFixture,
  previousBriefingFixture,
} from "./fixtures/briefing";

/*
 * RL-01 STEP-007 · spec T10 — `/briefing` 오늘의 브리핑 화면.
 *
 * 고정 응답은 `mockApi`(미등록 경로는 404) 위에 건 `mockBriefing`이며 실제 백엔드에 연결하지
 * 않는다. 화면 시계는 `BRIEFING_NOW`로 고정해 마감 D-n이 결정적이다. 기대값은 화면 코드를
 * 가져오지 않고 fixture 값으로 직접 적었다.
 *
 * 항목 번호(fixture): 1·2·3 반응 대기(사전규격·입찰공고·발주계획), 4 채택, 5 무시, 6 나중에,
 * 7·8 추적 변화.
 */

const ID = Object.fromEntries([1, 2, 3, 4, 5, 6, 7, 8].map((index) => [index, briefingItemId(index)])) as Record<number, string>;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const TITLE = {
  1: "클라우드 기반 업무시스템 고도화 사전규격",
  2: "정보시스템 통합 유지관리 용역",
  3: "2027년 차세대 민원 포털 구축",
  7: "도로 관리 시스템 재구축(정정공고)",
} as const;
const NOT_FOUND = "이 환경에서 만들어진 브리핑이 없어요";

test.beforeEach(async ({ page }) => {
  await page.route("**://fonts.googleapis.com/**", (route) => route.fulfill({ status: 200, contentType: "text/css", body: "" }));
});

async function openBriefing(page: Page, search = "", options: BriefingMockOptions = {}) {
  await page.clock.setFixedTime(new Date(BRIEFING_NOW));
  await mockApi(page);
  const trace = await mockBriefing(page, options);
  // 외부로 나가는 요청이 있으면 테스트가 실패하게 한다.
  const external: string[] = [];
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (url.hostname !== "127.0.0.1") external.push(request.url());
  });
  await page.goto(`/briefing${search}`);
  return { trace, external };
}

// 마감 묶음과 추적 변화의 RecordTable 행이 선택과 키보드 초점을 받는다.
const row = (page: Page, itemId: string) => page.locator(`tr.briefing-row[data-row-key="${itemId}"]`);
const rowTitle = (page: Page, itemId: string) => row(page, itemId).locator(".briefing-row-title");
const rowIds = (page: Page) => page.locator("tr.briefing-row").evaluateAll((nodes) => nodes.map((node) => node.getAttribute("data-row-key")));
/** 탭·데이터가 바뀐 직후의 행 목록은 렌더가 끝날 때까지 기다려 비교한다. */
const expectRows = (page: Page, ids: Array<string | undefined>) => expect.poll(() => rowIds(page)).toEqual(ids);
const peek = (page: Page) => page.getByRole("complementary", { name: "선택한 공고" });
/** 행 안의 반응 버튼 묶음(채택 · 나중에 · 무시). */
const reactions = (page: Page, itemId: string) => row(page, itemId).locator(".briefing-reactions");
const toast = (page: Page) => page.locator(".toast");
const tab = (page: Page, name: RegExp) => page.getByRole("tab", { name });
const count = (page: Page, key: "pending" | "accepted" | "ignored" | "later") => page.getByTestId(`briefing-count-${key}`);
/** 담당자 이름은 사이드바 담당자 칸 하나다(최종 시안). 칸을 열어 적고 닫는다. */
async function setActor(page: Page, name = "최담당") {
  await page.locator("aside.sidebar .sidebar-actor-trigger").click();
  await page.locator("aside.sidebar").getByLabel("담당자 이름").fill(name);
  await page.locator("aside.sidebar").getByRole("button", { name: "닫기", exact: true }).click();
}

async function selectedParam(page: Page) {
  return new URL(page.url()).searchParams.get("selected");
}

test("T10: 뷰 탭은 반응 필터이고 건수는 클라이언트가 센다 · 마감 묶음과 추적 변화 묶음", async ({ page }) => {
  const { trace, external } = await openBriefing(page);

  // 패널 헤더(최종 시안): 화면 이름 · 문장형 제목(반응 대기 건수) · 설명(마감 전 건수·가장 가까운 마감) · 수집 상태.
  await expect(page.locator("header.topbar h1")).toHaveText("오늘의 브리핑");
  await expect(page.locator(".topbar-location-date")).toHaveText("10월 16일 금요일");
  await expect(page.getByTestId("page-header-description")).toHaveText("마감 전인 건은 2건이고, 가장 가까운 마감은 10월 18일이에요.");
  await expect(page.getByTestId("briefing-collection-status")).toHaveText("수집 완료 · 10월 15일 기준");
  expect(trace.requests[0]).toBe("GET /api/briefings/latest");

  // 탭 4개(시안 순서: 반응 대기 · 채택 · 나중에 · 무시)와 건수(추천 항목의 reaction만 센다).
  await expect(page.getByRole("tab")).toHaveCount(4);
  await expect(page.getByRole("tab")).toHaveText([/^반응 대기/, /^채택/, /^나중에/, /^무시/]);
  await expect(tab(page, /^반응 대기/)).toHaveAttribute("aria-selected", "true");
  await expect(count(page, "pending")).toHaveText("3");
  await expect(count(page, "accepted")).toHaveText("1");
  await expect(count(page, "ignored")).toHaveText("1");
  await expect(count(page, "later")).toHaveText("1");

  // 기본 탭 = 반응 대기: 마감 전 2건(1·2) → 마감일 없음 1건(3, 발주계획) → 추적 변화 2건.
  await expectRows(page, [ID[1], ID[2], ID[3], ID[7], ID[8]]);
  await expect(page.getByRole("heading", { level: 2 })).toHaveText(["마감 전", "마감일이 정해지지 않았어요", "추적 중인 사업의 변화"]);
  await expect(page.getByTestId("briefing-group-count-open")).toHaveText("2건");
  await expect(page.getByTestId("briefing-group-count-undated")).toHaveText("1건");
  const open = page.getByRole("table", { name: "마감 전 추천" });
  await expect(open.getByRole("columnheader")).toHaveText(["사업명", "발주기관", "반응", "마감"]);
  await expect(open.locator("tbody tr")).toHaveCount(2);
  await expect(page.getByTestId("briefing-tracked-count")).toHaveText("2");
  await expect(page.getByRole("table", { name: "추적 중인 사업의 변화" }).locator("tbody tr")).toHaveCount(2);

  // 채택 탭: 채택 1건만, 추적 변화 묶음은 반응이 없으므로 이 탭에 없다. URL과 동기화된다.
  await tab(page, /^채택/).click();
  await expect(page).toHaveURL(/[?&]view=accepted/);
  await expect(tab(page, /^채택/)).toHaveAttribute("aria-selected", "true");
  await expectRows(page, [ID[4]]);
  await expect(reactions(page, ID[4]).getByRole("button", { name: "채택", exact: true })).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByRole("heading", { name: /^추적 중인 사업의 변화/ })).toHaveCount(0);

  await tab(page, /^무시/).click();
  await expectRows(page, [ID[5]]);
  await tab(page, /^나중에/).click();
  await expectRows(page, [ID[6]]);
  await expect(page).toHaveURL(/[?&]view=later/);

  // 허용값 밖의 view는 기본 탭(반응 대기)으로 본다.
  await page.goto("/briefing?view=nonsense");
  await expect(tab(page, /^반응 대기/)).toHaveAttribute("aria-selected", "true");
  await expectRows(page, [ID[1], ID[2], ID[3], ID[7], ID[8]]);

  expect(external).toEqual([]);
});

test("T10: 행 칸 — 단계·마감은 글자, 마감 전은 굵은 D-n · 반응 버튼은 행 안에 있다", async ({ page }) => {
  await openBriefing(page);

  // 사전규격 · D-2 · 의견 마감. 단계·마감은 표식이 아니라 글자다(최종 시안).
  const r1 = row(page, ID[1]);
  await expect(r1.locator(".briefing-row-title")).toHaveText(TITLE[1]);
  await expect(r1.locator(".briefing-row-agency")).toHaveText("대구광역시");
  await expect(r1.locator(".briefing-row-amount")).toHaveText("4.8억원");
  await expect(r1.locator(".briefing-row-verdict")).toHaveText("분석 대기");
  await expect(r1.locator(".briefing-row-stage")).toHaveText("사전규격");
  await expect(r1.locator(".briefing-deadline")).toHaveText("D-2 · 10월 18일 의견 마감");
  await expect(r1.locator(".briefing-deadline")).toHaveAttribute("data-urgent", "true");
  await expect(r1.locator(".briefing-dday-text")).toHaveText("D-2");
  // 반응 버튼 3개(채택 · 나중에 · 무시). 아직 반응이 없으므로 아무것도 눌려 있지 않다.
  await expect(reactions(page, ID[1]).getByRole("button")).toHaveText(["채택", "나중에", "무시"]);
  for (const name of ["채택", "나중에", "무시"]) {
    await expect(reactions(page, ID[1]).getByRole("button", { name, exact: true })).toHaveAttribute("aria-pressed", "false");
  }
  // 마감 전 묶음의 채택은 주 버튼이다.
  await expect(reactions(page, ID[1]).getByRole("button", { name: "채택", exact: true })).toHaveClass(/is-primary/);

  // 입찰공고 · 마감 전이면 날수와 관계없이 D-n을 강조한다(시안 D-12).
  const r2 = row(page, ID[2]);
  await expect(r2.locator(".briefing-row-stage")).toHaveText("입찰공고");
  await expect(r2.locator(".briefing-deadline")).toHaveText("D-12 · 10월 28일 마감");

  // 발주계획 · "n월 발주 예정" · 금액이 없으면 0이 아니라 "금액 미공개". 마감일 없음 묶음이라 채택은 옅은 채움이다.
  const r3 = row(page, ID[3]);
  await expect(r3.locator(".briefing-row-stage")).toHaveText("발주계획");
  await expect(r3.locator(".briefing-deadline")).toHaveText("2월 발주 예정");
  await expect(r3.locator(".briefing-deadline")).toHaveAttribute("data-urgent", "false");
  await expect(r3.locator(".briefing-row-agency")).toHaveText("대구광역시 수성구");
  await expect(r3.locator(".briefing-row-amount")).toHaveText("금액 미공개");
  await expect(r3.locator(".briefing-row-verdict")).toHaveText("연차 추적");
  await expect(reactions(page, ID[3]).getByRole("button", { name: "채택", exact: true })).not.toHaveClass(/is-primary/);

  // 다른 탭의 마감 전 행도 같은 규칙이다(D-7·D-8).
  await tab(page, /^채택/).click();
  await expect(row(page, ID[4]).locator(".briefing-dday-text")).toHaveText("D-7");
  await tab(page, /^무시/).click();
  await expect(row(page, ID[5]).locator(".briefing-dday-text")).toHaveText("D-8");

  // 추적 변화 묶음: 반응 버튼 대신 "반응 없음" 글자, 바뀐 항목이 보조 줄에 있다.
  await tab(page, /^반응 대기/).click();
  const t7 = row(page, ID[7]);
  await expect(t7.getByText("반응 없음")).toBeVisible();
  await expect(t7.locator("[data-reaction]")).toHaveCount(0);
  await expect(t7.getByText("바뀐 항목 · 마감")).toBeVisible();
  await expect(row(page, ID[8]).getByText("바뀐 항목 · 제목, 예산")).toBeVisible();
});

test("T10: 행을 누르면 피크가 열린다 — 머리·제목·보조·판정 이름·반응 기록·왜 추천·자세히 보기만", async ({ page }) => {
  await openBriefing(page);
  await expect(peek(page)).toHaveCount(0);

  await rowTitle(page, ID[1]).click();
  await expect.poll(() => selectedParam(page)).toBe(ID[1]);
  await expect(row(page, ID[1])).toHaveAttribute("tabindex", "0");
  await expect(row(page, ID[1])).toHaveAttribute("aria-current", "true");
  await expect(row(page, ID[2])).not.toHaveAttribute("aria-current", "true");

  const panel = peek(page);
  await expect(panel.getByRole("heading", { level: 3 })).toHaveText(TITLE[1]);
  await expect(panel.locator(".briefing-peek-stage")).toHaveText("사전규격");
  await expect(panel.locator(".briefing-dday")).toHaveText("D-2");
  await expect(panel.locator(".briefing-dday")).toHaveAttribute("data-urgent", "true");
  await expect(panel.locator(".workbench-facts dt")).toHaveText(["발주기관", "금액", "마감", "판정", "반응 기록"]);
  await expect(panel.locator(".workbench-facts dd:not(:has([data-testid]))"))
    .toHaveText(["대구광역시", "4.8억원", "10월 18일 (일) 18:00 의견 마감"]);

  // 반응 버튼은 행 안에만 있다(최종 시안). 피크는 판정 이름(서버 글자 그대로)과 반응 기록 한 줄을 보인다.
  await expect(panel.locator("[data-reaction]")).toHaveCount(0);
  await expect(panel.getByTestId("briefing-peek-verdict")).toHaveText("분석 대기");
  await expect(panel.getByTestId("briefing-peek-record")).toHaveText("아직 반응이 없어요");

  // 왜 추천: 키워드·비슷한 실적 n건·기관 거래 이력(칩 3개).
  await expect(panel.getByRole("heading", { name: "왜 추천" })).toBeVisible();
  await expect(panel.locator(".briefing-chip")).toHaveText(["키워드 · 클라우드", "비슷한 실적 2건", "기관 거래 이력 · 대구광역시"]);

  // 자세히 보기는 record_path로 간다.
  await expect(panel.getByRole("link", { name: "자세히 보기" })).toHaveAttribute("href", "/opportunities/501");

  // RL-01이 그리지 않는 요소: 판정 블록(사유·확인할 것)·다음 행동·상단바 공고 추가/공유/가져오기·보기 설정.
  await expect(panel.getByText(/확인할 것|다음 행동/)).toHaveCount(0);
  for (const name of ["공고 추가", "공유", "가져오기", "보기 설정"]) {
    await expect(page.getByRole("button", { name })).toHaveCount(0);
    await expect(page.getByRole("link", { name })).toHaveCount(0);
  }

  // 다른 행을 누르면 피크가 그 행으로 바뀐다. 반응 기록은 한 줄이다.
  await page.getByRole("tab", { name: /^채택/ }).click();
  await expect(peek(page)).toHaveCount(0);
  await rowTitle(page, ID[4]).click();
  await expect(reactions(page, ID[4]).getByRole("button", { name: "채택", exact: true })).toHaveAttribute("aria-pressed", "true");
  await expect(panel.getByTestId("briefing-peek-record")).toHaveText("김담당이 채택 · 08:41");
  await expect(panel.locator(".briefing-peek-title")).toHaveText(LONG_TITLE);
  // 이유 칩이 없는 항목은 "왜 추천" 빈 블록을 그리지 않는다.
  await expect(panel.getByRole("heading", { name: "왜 추천" })).toHaveCount(0);

  // 닫기 버튼.
  await panel.getByRole("button", { name: "닫기" }).click();
  await expect(peek(page)).toHaveCount(0);
  await expect.poll(() => selectedParam(page)).toBeNull();
});

test("T10: ?selected=<item_id>로 피크를 연다 · 속한 탭을 고르고 모르는 id는 무시한다", async ({ page }) => {
  await openBriefing(page, `?selected=${ID[2]}`);
  await expect(peek(page).getByRole("heading", { level: 3 })).toHaveText(TITLE[2]);
  await expect(row(page, ID[2])).toHaveAttribute("aria-current", "true");
  await expect(tab(page, /^반응 대기/)).toHaveAttribute("aria-selected", "true");

  // view 없이 채택 항목을 선택하면 그 항목이 속한 탭(채택)이 열리고 주소에 고정된다.
  await page.goto(`/briefing?selected=${ID[4]}`);
  await expect(tab(page, /^채택/)).toHaveAttribute("aria-selected", "true");
  await expect(row(page, ID[4])).toHaveAttribute("aria-current", "true");
  await expect(page).toHaveURL(/[?&]view=accepted/);

  // 추적 변화 행 선택: 버튼·반응 기록이 없고 바뀐 항목이 보인다.
  await page.goto(`/briefing?selected=${ID[7]}`);
  const panel = peek(page);
  await expect(panel.getByRole("heading", { level: 3 })).toHaveText(TITLE[7]);
  await expect(row(page, ID[7]).locator("[data-reaction]")).toHaveCount(0);
  await expect(panel.getByTestId("briefing-peek-record")).toHaveCount(0);
  await expect(panel.getByRole("heading", { name: "바뀐 항목" })).toBeVisible();
  await expect(panel.locator(".briefing-chip")).toHaveText(["마감"]);
  await expect(panel.getByRole("button", { name: /채택|무시|나중에/ })).toHaveCount(0);

  // 없는 id는 조용히 무시한다(피크도 오류도 없다).
  await page.goto("/briefing?selected=00000000-0000-4000-8000-000000000000");
  await expect(row(page, ID[1])).toBeVisible();
  await expect(peek(page)).toHaveCount(0);
});

test("T10: 키보드 1·2·H·Z — 저장 본문·담당자·다음 행 이동·5초 토스트 되돌리기", async ({ page }) => {
  const { trace } = await openBriefing(page);
  await setActor(page, "최담당");

  await rowTitle(page, ID[1]).click();
  await expect(peek(page)).toContainText(TITLE[1]);

  // 1 = 채택: expected_revision·reaction·UUID request_id, actor 헤더.
  await page.keyboard.press("1");
  await expect.poll(() => trace.patches.length).toBe(1);
  expect(trace.patches[0].itemId).toBe(ID[1]);
  expect(trace.patches[0].actor).toBe("최담당");
  expect(Object.keys(trace.patches[0].body).sort()).toEqual(["expected_revision", "reaction", "request_id"]);
  expect(trace.patches[0].body).toMatchObject({ reaction: "채택", expected_revision: 0 });
  expect(String(trace.patches[0].body.request_id)).toMatch(UUID);

  // 서버 응답으로 건수가 바뀌고(대기 3→2, 채택 1→2).
  await expect(count(page, "pending")).toHaveText("2");
  await expect(count(page, "accepted")).toHaveText("2");
  // 행은 이 탭을 떠났고 다음 행(2번)으로 선택·초점이 옮겨졌다.
  await expect(row(page, ID[1])).toHaveCount(0);
  await expect.poll(() => selectedParam(page)).toBe(ID[2]);
  await expect(peek(page)).toContainText(TITLE[2]);
  await expect(row(page, ID[2])).toBeFocused();
  // 5초 토스트 + 되돌리기.
  await expect(toast(page)).toContainText("반응을 저장했어요 · 채택");
  await expect(toast(page).getByRole("button", { name: "되돌리기" })).toBeVisible();

  // 2 = 무시.
  await page.keyboard.press("2");
  await expect.poll(() => trace.patches.length).toBe(2);
  expect(trace.patches[1].itemId).toBe(ID[2]);
  expect(trace.patches[1].body).toMatchObject({ reaction: "무시", expected_revision: 0 });
  expect(String(trace.patches[1].body.request_id)).toMatch(UUID);
  expect(trace.patches[1].body.request_id).not.toBe(trace.patches[0].body.request_id);
  await expect(count(page, "ignored")).toHaveText("2");
  await expect.poll(() => selectedParam(page)).toBe(ID[3]);

  // H = 나중에(대문자 Shift+H도 같은 키다).
  await page.keyboard.press("h");
  await expect.poll(() => trace.patches.length).toBe(3);
  expect(trace.patches[2].itemId).toBe(ID[3]);
  expect(trace.patches[2].body).toMatchObject({ reaction: "나중에", expected_revision: 0 });
  await expect(count(page, "pending")).toHaveText("0");
  await expect(count(page, "later")).toHaveText("2");
  await expect(page.getByText("반응 대기 항목이 없어요")).toBeVisible();
  // 다음 행은 추적 변화 묶음(7번)이다. 이 행에는 반응이 없다.
  await expect.poll(() => selectedParam(page)).toBe(ID[7]);
  await expect(row(page, ID[7]).locator("[data-reaction]")).toHaveCount(0);

  // 추적 변화 행에서 1을 눌러도 저장하지 않는다(PATCH가 늘지 않는다는 것은 아래 Z가 3번 항목의
  // 되돌리기 하나만 보낸다는 것으로 확인한다).
  await page.keyboard.press("1");

  // Z = 직전 반응을 이전 값(대기)으로 되돌리는 새 PATCH. 3번 항목의 revision은 1이다.
  await page.keyboard.press("z");
  await expect.poll(() => trace.patches.length).toBe(4);
  expect(trace.patches[3].itemId).toBe(ID[3]);
  expect(trace.patches[3].body).toMatchObject({ reaction: "대기", expected_revision: 1 });
  expect(String(trace.patches[3].body.request_id)).toMatch(UUID);
  await expect(count(page, "pending")).toHaveText("1");
  await expect(count(page, "later")).toHaveText("1");
  await expect.poll(() => selectedParam(page)).toBe(ID[3]);
  await expect(toast(page)).toContainText("되돌렸어요");
  await expect(toast(page).getByRole("button", { name: "되돌리기" })).toHaveCount(0);

  // 되돌린 뒤에는 되돌릴 것이 없다. Z를 다시 눌러도 저장하지 않는다 — 이어서 2를 누르면
  // 5번째 PATCH가 바로 이 키 하나의 것이다.
  await page.keyboard.press("z");
  await page.keyboard.press("2");
  await expect.poll(() => trace.patches.length).toBe(5);
  expect(trace.patches[4].body).toMatchObject({ reaction: "무시", expected_revision: 2 });

  // 서버 상태: 반응은 추적 상태와 무관한 항목 필드이고 이벤트 revision은 항목마다 올라갔다.
  const server = trace.server(BRIEFING_DATE)!;
  expect(server.items.find((entry) => entry.item_id === ID[1])).toMatchObject({ reaction: "채택", reacted_by: "최담당", revision: 1 });
  expect(server.items.find((entry) => entry.item_id === ID[3])).toMatchObject({ reaction: "무시", revision: 3 });
});

test("T10: 토스트 되돌리기 버튼 · 5초 뒤 사라지면 Z는 아무것도 하지 않는다", async ({ page }) => {
  const { trace } = await openBriefing(page);
  await setActor(page);
  await rowTitle(page, ID[1]).click();
  await page.keyboard.press("1");
  await expect(toast(page)).toContainText("반응을 저장했어요 · 채택");

  // 토스트의 되돌리기 버튼 = 이전 값(대기)으로 새 PATCH.
  await toast(page).getByRole("button", { name: "되돌리기" }).click();
  await expect.poll(() => trace.patches.length).toBe(2);
  expect(trace.patches[1].itemId).toBe(ID[1]);
  expect(trace.patches[1].body).toMatchObject({ reaction: "대기", expected_revision: 1 });
  await expect(count(page, "pending")).toHaveText("3");
  await expect(row(page, ID[1])).toBeVisible();
  await expect.poll(() => selectedParam(page)).toBe(ID[1]);

  // 다시 반응하고 토스트가 5초 안팎에 사라지는지 본다. 포인터가 토스트 위에 남아 있으면 읽는 동안
  // 타이머가 멈추므로(Toast hold) 치워 둔다.
  await page.mouse.move(0, 0);
  await page.keyboard.press("2");
  await expect(toast(page)).toContainText("반응을 저장했어요 · 무시");
  const shownAt = Date.now();
  await expect(toast(page)).toBeHidden({ timeout: 9_000 });
  const elapsed = Date.now() - shownAt;
  expect(elapsed).toBeGreaterThan(3_000);
  expect(elapsed).toBeLessThan(7_500);
  const before = trace.patches.length;
  // 토스트가 없으면 Z는 되돌릴 것이 없다. 이어지는 1(다음 행 채택)이 곧바로 다음 PATCH다.
  await page.keyboard.press("z");
  await page.keyboard.press("1");
  await expect.poll(() => trace.patches.length).toBe(before + 1);
  expect(trace.patches[before].body).toMatchObject({ reaction: "채택" });
  expect(trace.patches[before].itemId).not.toBe(ID[1]);
});

test("T10: 이미 선택된 반응을 다시 누르면 대기로 돌아간다 · 마우스 버튼도 같은 저장 경로", async ({ page }) => {
  const { trace } = await openBriefing(page, "?view=accepted");
  await setActor(page, "김담당");
  await rowTitle(page, ID[4]).click();
  const accept = reactions(page, ID[4]).getByRole("button", { name: "채택", exact: true });
  await expect(accept).toHaveAttribute("aria-pressed", "true");

  // 눌린 채택을 다시 누르면 대기. 채택 탭을 떠난다.
  await accept.click();
  await expect.poll(() => trace.patches.length).toBe(1);
  expect(trace.patches[0]).toMatchObject({ itemId: ID[4], actor: "김담당", body: { reaction: "대기", expected_revision: 1 } });
  await expect(toast(page)).toContainText("반응을 취소했어요");
  await expect(count(page, "accepted")).toHaveText("0");
  await expect(count(page, "pending")).toHaveText("4");
  await expect(page.getByText("채택 항목이 없어요")).toBeVisible();

  // 되돌리기 → 채택으로 복원, 선택이 그 행으로 돌아온다.
  await toast(page).getByRole("button", { name: "되돌리기" }).click();
  await expect.poll(() => trace.patches.length).toBe(2);
  expect(trace.patches[1].body).toMatchObject({ reaction: "채택", expected_revision: 2 });
  await expect(row(page, ID[4])).toBeVisible();
  await expect(accept).toHaveAttribute("aria-pressed", "true");
  await expect(peek(page).getByTestId("briefing-peek-record")).toContainText("김담당이 채택");

  // 마우스로 무시 버튼: 같은 PATCH 계약.
  await reactions(page, ID[4]).getByRole("button", { name: "무시", exact: true }).click();
  await expect.poll(() => trace.patches.length).toBe(3);
  expect(trace.patches[2].body).toMatchObject({ reaction: "무시", expected_revision: 3 });
  await expect(count(page, "ignored")).toHaveText("2");
});

test("T10: 담당자 이름이 없으면 저장하지 않고 입력 칸으로 안내한다 · 입력 중에는 단축키가 동작하지 않는다", async ({ page }) => {
  const { trace } = await openBriefing(page);
  await rowTitle(page, ID[1]).click();

  await page.keyboard.press("1");
  await expect(toast(page)).toContainText("담당자 이름을 입력한 뒤 다시 눌러 주세요");
  // 이름은 사이드바 담당자 칸에서 받는다. 칸이 열리고 입력에 초점이 간다.
  await expect(page.locator("aside.sidebar").getByLabel("담당자 이름")).toBeFocused();
  expect(trace.patches).toHaveLength(0);

  // 입력 칸에서 1·2·h·z를 쳐도 반응이 저장되지 않고 글자로 들어간다.
  await page.keyboard.type("12hz");
  await expect(page.locator("aside.sidebar").getByLabel("담당자 이름")).toHaveValue("12hz");
  expect(trace.patches).toHaveLength(0);

  // 이름을 고치고 행으로 돌아와 누르면 저장된다. 한글 이름은 안전하게 인코딩돼 전달된다.
  await page.locator("aside.sidebar").getByLabel("담당자 이름").fill("홍길동");
  await rowTitle(page, ID[1]).click();
  await page.keyboard.press("1");
  await expect.poll(() => trace.patches.length).toBe(1);
  expect(trace.patches[0].actor).toBe("홍길동");
  expect(trace.patches[0].headers["x-bidops-actor-name-format"]).toBe("utf-8-percent-v1");
});

test("T10: Enter는 피크를 열고 한 번 더 누르면 레코드로 간다 · Esc는 피크를 닫는다 · ↑↓는 행을 옮긴다", async ({ page }) => {
  await openBriefing(page);

  // 초점이 행에 있으면 Enter = 피크 열기(선택), 이미 열린 행에서 Enter = 레코드.
  await row(page, ID[1]).focus();
  await page.keyboard.press("Enter");
  await expect.poll(() => selectedParam(page)).toBe(ID[1]);
  await expect(peek(page)).toContainText(TITLE[1]);

  // ↓ = 다음 행 선택(피크 따라감, 초점도 따라감).
  await page.keyboard.press("ArrowDown");
  await expect.poll(() => selectedParam(page)).toBe(ID[2]);
  await expect(row(page, ID[2])).toBeFocused();
  await expect(peek(page)).toContainText(TITLE[2]);
  await page.keyboard.press("ArrowUp");
  await expect.poll(() => selectedParam(page)).toBe(ID[1]);

  // Esc = 피크 닫기.
  await page.keyboard.press("Escape");
  await expect(peek(page)).toHaveCount(0);
  await expect.poll(() => selectedParam(page)).toBeNull();

  // 열린 피크에서 Enter → 레코드(record_path).
  await row(page, ID[1]).focus();
  await page.keyboard.press("Enter");
  await expect(peek(page)).toBeVisible();
  await page.keyboard.press("Enter");
  // RL-02: record_path(`/opportunities/<id>`)는 레코드 활동 탭으로 replace 리다이렉트된다.
  await expect(page).toHaveURL(/\/opportunities\/501\/activity$/);
});

test("T10: 409 version_conflict는 조용히 덮어쓰지 않고 다시 읽은 뒤 확인하게 한다", async ({ page }) => {
  const { trace } = await openBriefing(page);
  await setActor(page, "최담당");
  await rowTitle(page, ID[1]).click();
  await expect(peek(page)).toContainText(TITLE[1]);
  const readsBefore = trace.requests.filter((entry) => entry === "GET /api/briefings/latest").length;

  // 화면은 모르는 사이에 다른 담당자가 같은 항목에 먼저 반응한다(서버 revision 0 → 1).
  trace.externalReact(ID[1], "무시", "박기획");

  await page.keyboard.press("1");
  await expect.poll(() => trace.patches.length).toBe(1);
  expect(trace.patches[0].body).toMatchObject({ reaction: "채택", expected_revision: 0 });
  await expect(toast(page)).toContainText("다른 담당자가 먼저 반응했어요");
  // 서버 상태는 덮어쓰지 않았다: 먼저 남긴 무시가 그대로다.
  expect(trace.server(BRIEFING_DATE)!.items[0]).toMatchObject({ reaction: "무시", reacted_by: "박기획", revision: 1 });

  // 화면은 최신 상태를 다시 읽었다: 1번은 반응 대기에서 빠지고 피크는 먼저 남긴 반응을 보여 준다.
  await expect.poll(() => trace.requests.filter((entry) => entry === "GET /api/briefings/latest").length).toBeGreaterThan(readsBefore);
  await expect(count(page, "pending")).toHaveText("2");
  await expect(count(page, "ignored")).toHaveText("2");
  await expect(row(page, ID[1])).toHaveCount(0);
  await expect(tab(page, /^반응 대기/)).toHaveAttribute("aria-selected", "true");
  await expect(peek(page).getByTestId("briefing-peek-record")).toContainText("박기획이 무시");
  // 되돌릴 저장이 없었으므로 토스트에 되돌리기도 없다.
  await expect(toast(page).getByRole("button", { name: "되돌리기" })).toHaveCount(0);

  // 읽은 뒤 사람이 다시 누르면 최신 revision(1)으로 저장된다.
  await page.keyboard.press("1");
  await expect.poll(() => trace.patches.length).toBe(2);
  expect(trace.patches[1].body).toMatchObject({ reaction: "채택", expected_revision: 1 });
  await expect(count(page, "accepted")).toHaveText("2");
});

test("T10: 추적 변화 행에는 반응 버튼이 없고 서버도 반응을 받지 않는다", async ({ page }) => {
  const { trace } = await openBriefing(page);
  await setActor(page);
  // 추적 변화는 키보드로 고를 수 있는 표 행으로 표시한다.
  const tracked = page.getByRole("table", { name: "추적 중인 사업의 변화" });
  await expect(tracked.locator("tbody tr[data-row-key][tabindex]")).toHaveCount(2);
  await expect(tracked.locator("[data-reaction]")).toHaveCount(0);
  await expect(tracked.getByRole("button")).toHaveCount(0);

  // 추적 변화 행을 눌러 열어도 반응 버튼이 없고, 키 1·2·H는 저장하지 않는다.
  await rowTitle(page, ID[7]).click();
  await expect(peek(page)).toContainText(TITLE[7]);
  await expect(peek(page).getByRole("button", { name: /채택|무시|나중에/ })).toHaveCount(0);
  await page.keyboard.press("1");
  await page.keyboard.press("2");
  await page.keyboard.press("h");
  // 아래 PATCH가 바로 이 키 하나의 것이다(앞의 세 키는 아무것도 보내지 않았다).
  await rowTitle(page, ID[1]).click();
  await expect(peek(page)).toContainText(TITLE[1]);
  await page.keyboard.press("1");
  await expect.poll(() => trace.patches.length).toBe(1);
  expect(trace.patches[0].itemId).toBe(ID[1]);
});

test("T10: 추천 0건이면 수집 정상 빈 상태를 보여 준다", async ({ page }) => {
  await openBriefing(page, "", { briefings: { [BRIEFING_DATE]: emptyBriefingFixture() } });
  await expect(page.getByRole("tabpanel").getByText("오늘 추천할 공고가 없어요 · 수집 정상", { exact: true })).toBeVisible();
  await expect(page.locator("header.topbar h1")).toHaveText("오늘의 브리핑");
  await expect(page.getByTestId("briefing-collection-status")).toHaveText("수집 완료 · 10월 15일 기준");
  await expect(page.getByText("오늘 수집이 끝나지 않았어요")).toHaveCount(0);
  await expect(page.locator("tr.briefing-row[data-row-key]")).toHaveCount(0);
  await expect(count(page, "pending")).toHaveText("0");
});

test("T10: 수집이 끝나지 않은 날은 경고 블록과 함께 항목도 보여 준다", async ({ page }) => {
  await openBriefing(page, "", { briefings: { [BRIEFING_DATE]: incompleteBriefingFixture("기준일 수집 회차 없음") } });
  const warning = page.getByRole("status", { name: "수집 상태" });
  await expect(warning).toContainText("오늘 수집이 끝나지 않았어요");
  await expect(warning).toContainText("기준일 수집 회차 없음");
  // 헤더의 수집 상태도 완료라고 말하지 않는다(브리핑 status 그대로).
  await expect(page.getByTestId("briefing-collection-status")).toHaveText("수집이 끝나지 않았어요 · 10월 15일 기준");
  // 항목은 그래도 만들어진다. 추천 0건 빈 상태 문구("수집 정상")는 나오지 않는다.
  await expectRows(page, [ID[1], ID[2], ID[3], ID[7], ID[8]]);
  await expect(page.getByText("수집 정상")).toHaveCount(0);

  // 중복 회차 사유도 서버 문구 그대로 보인다.
  const second = await page.context().newPage();
  await second.clock.setFixedTime(new Date(BRIEFING_NOW));
  await mockApi(second);
  await mockBriefing(second, { briefings: { [BRIEFING_DATE]: incompleteBriefingFixture("회차 중복") } });
  await second.goto("/briefing");
  await expect(second.getByRole("status", { name: "수집 상태" })).toContainText("회차 중복");
});

test("T10: 브리핑이 없으면 현재 자리 화면의 안내 문구를 보여 준다(최신·날짜·잘못된 날짜)", async ({ page }) => {
  // 서버에 브리핑이 하나도 없다: latest 404 `briefing_not_found`.
  await openBriefing(page, "", { briefings: {} });
  await expect(page.getByText(NOT_FOUND)).toBeVisible();
  await expect(page.getByRole("link", { name: "사전규격 목록 열기" })).toHaveAttribute("href", "/pre-specs");
  await expect(page.getByTestId("briefing-collection-status")).toHaveCount(0);
  await expect(page.locator("header.topbar h1")).toHaveText("오늘의 브리핑");

  // 없는 날짜: 404. 최신 브리핑으로 돌아가는 링크가 있다.
  await page.goto("/briefing?date=2026-09-01");
  await expect(page.getByText(NOT_FOUND)).toBeVisible();
  await expect(page.getByRole("link", { name: "최신 브리핑 열기" })).toHaveAttribute("href", "/briefing");

  // 형식이 잘못된 날짜는 서버를 부르지 않고 같은 안내를 보여 준다.
  await page.goto("/briefing?date=abc");
  await expect(page.getByText(NOT_FOUND)).toBeVisible();
  await expect(page.getByText(/날짜 형식이 올바르지 않아요/)).toBeVisible();
});

test("T10: 브리핑 API를 mock하지 않아도(고정 응답 404) 안내 문구가 나오고 외부로 새지 않는다", async ({ page }) => {
  await page.clock.setFixedTime(new Date(BRIEFING_NOW));
  await mockApi(page);
  const external: string[] = [];
  page.on("request", (request) => {
    if (new URL(request.url()).hostname !== "127.0.0.1") external.push(request.url());
  });
  await page.goto("/briefing");
  await expect(page.getByText(NOT_FOUND)).toBeVisible();
  expect(external).toEqual([]);
});

test("T10: 날짜 이동 — 이전 브리핑은 직전 평일이고 최신 브리핑으로 돌아온다", async ({ page }) => {
  const { trace } = await openBriefing(page);
  const previous = page.getByRole("link", { name: "이전 브리핑" });
  await expect(previous).toHaveAttribute("href", `/briefing?date=${BRIEFING_PREVIOUS_DATE}`);
  await expect(page.getByRole("link", { name: "최신 브리핑" })).toHaveCount(0);

  await previous.click();
  await expect(page).toHaveURL(new RegExp(`date=${BRIEFING_PREVIOUS_DATE}`));
  // 지난 날짜의 브리핑은 `오늘`이라고 말하지 않는다.
  await expect(page.locator(".topbar-location-date")).toHaveText("10월 15일 목요일");
  await expect(page.locator("header.topbar h1")).toHaveText("오늘의 브리핑");
  // 요청 기록은 재시도하지 않는 단언이라 데이터가 그려진 뒤에 읽는다(URL 변경은 fetch보다 먼저 일어난다).
  expect(trace.requests).toContain(`GET /api/briefings/${BRIEFING_PREVIOUS_DATE}`);
  await expectRows(page, [briefingItemId(21)]);
  await page.getByRole("link", { name: "최신 브리핑" }).click();
  await expect(page.locator(".topbar-location-date")).toHaveText("10월 16일 금요일");

  // 월요일 브리핑의 이전은 지난 금요일이다(주말에는 브리핑이 없다).
  const second = await page.context().newPage();
  await second.clock.setFixedTime(new Date(BRIEFING_NOW));
  await mockApi(second);
  await mockBriefing(second, {
    briefings: { [BRIEFING_MONDAY_DATE]: mondayBriefingFixture(), [BRIEFING_DATE]: briefingFixture(), [BRIEFING_PREVIOUS_DATE]: previousBriefingFixture() },
  });
  await second.goto(`/briefing?date=${BRIEFING_MONDAY_DATE}`);
  await expect(second.locator(".topbar-location-date")).toHaveText("10월 19일 월요일");
  await expect(second.getByRole("link", { name: "이전 브리핑" })).toHaveAttribute("href", `/briefing?date=${BRIEFING_DATE}`);
});

test("오늘 할 일에서 브리핑 추천을 열고 브리핑이 없으면 영역을 표시하지 않는다", async ({ page }) => {
  await mockApi(page);
  await mockBriefing(page);
  await page.goto("/");
  const briefing = page.locator('[data-block="briefing"]');
  await expect(briefing.getByRole("link", { name: "브리핑과 반응 이력 열기" })).toHaveAttribute("href", "/briefing");
  await briefing.getByRole("link", { name: new RegExp(TITLE[1]) }).click();
  await expect(peek(page)).toContainText(TITLE[1]);
  expect(new URL(page.url()).searchParams.get("date")).toBe(BRIEFING_DATE);
  await expect(page.locator('aside.sidebar [aria-current="page"]')).toHaveText("오늘 할 일");

  await expect(peek(page).getByRole("link", { name: "추적 검토 열기" })).toHaveCount(0);
  await page.goto(`/briefing?date=${BRIEFING_DATE}&selected=${ID[4]}`);
  await expect(peek(page).getByRole("link", { name: "추적 검토 열기" })).toHaveAttribute("href", "/pre-specs/9004");

  const second = await page.context().newPage();
  await mockApi(second);
  await mockBriefing(second, { briefings: {} });
  const unavailable = second.waitForResponse((response) => new URL(response.url()).pathname === "/api/briefings/latest");
  await second.goto("/");
  expect((await unavailable).status()).toBe(404);
  await expect(second.locator('[data-block="briefing"]')).toHaveCount(0);
});

// 실무 화면 DOM에 운영 정보가 없어야 한다(ui-spec §5, spec "표시 금지").
const FORBIDDEN_TEXT = [/policy/i, /score/i, /sha256/i, /graph_version/i, /generated_at/, /qwen/i, /gpt/i, /luna/i, /codex/i, /vllm/i, /unmeasured_reference/, /mock_reference/];
// 분모(`3 / 6`)·초 단위 시각(`08:00:17`)은 어디에도 없어야 한다.
const DENOMINATOR = /\d+\s*\/\s*\d+/;
const SECONDS = /\b\d{1,2}:\d{2}:\d{2}\b/;

test("T10: 표시 금지 문자열 — 정책·점수·초 단위 시각·분모·모델명이 DOM에 없다", async ({ page }) => {
  await openBriefing(page, `?selected=${ID[1]}`);
  await expect(peek(page)).toBeVisible();
  const checks = async (label: string) => {
    const text = await page.locator("body").innerText();
    const html = await page.locator("main").innerHTML();
    for (const pattern of FORBIDDEN_TEXT) {
      expect(text, `${label} 본문 ${pattern}`).not.toMatch(pattern);
      expect(html, `${label} 마크업 ${pattern}`).not.toMatch(pattern);
    }
    expect(text, `${label} 분모`).not.toMatch(DENOMINATOR);
    expect(text, `${label} 초 단위 시각`).not.toMatch(SECONDS);
    expect(text, `${label} 생성 시각 초`).not.toContain("08:00:17");
  };
  await checks("반응 대기");
  for (const [name, itemId] of [[/^채택/, ID[4]], [/^무시/, ID[5]], [/^나중에/, ID[6]]] as const) {
    await tab(page, name).click();
    await rowTitle(page, itemId).click();
    await expect(peek(page)).toBeVisible();
    await checks(String(name));
  }
  await tab(page, /^반응 대기/).click();
  await rowTitle(page, ID[7]).click();
  await checks("추적 변화");
});

for (const viewport of [{ width: 1280, height: 800 }, { width: 1440, height: 900 }]) {
  test(`T10: 구조 ${viewport.width}x${viewport.height} — 가로 넘침 없음 · h1 하나 · 행 묶음과 피크 폭`, async ({ page }) => {
    await page.setViewportSize(viewport);
    await openBriefing(page, `?selected=${ID[4]}&view=accepted`);
    await expect(peek(page)).toBeVisible();

    await expect(page.locator("h1")).toHaveCount(1);
    await expect(page.locator("header.topbar h1")).toHaveText("오늘의 브리핑");
    await expect(page.locator("tr.briefing-row[data-row-key]")).toHaveCount(1);

    const geometry = await page.evaluate(() => {
      const rect = (selector: string) => {
        const element = document.querySelector(selector);
        if (!element) return null;
        const box = element.getBoundingClientRect();
        return { left: box.left, right: box.right, top: box.top, bottom: box.bottom, width: box.width };
      };
      return {
        pageOverflow: document.documentElement.scrollWidth - window.innerWidth,
        canvasOverflow: (() => {
          const canvas = document.querySelector("main.page-canvas");
          return canvas ? canvas.scrollWidth - canvas.clientWidth : null;
        })(),
        listOverflow: (() => {
          const list = document.querySelector(".briefing-list");
          return list ? list.scrollWidth - list.clientWidth : null;
        })(),
        workspace: rect(".briefing-workspace"),
        list: rect(".briefing-workspace > .review-split-list"),
        peek: rect(".briefing-workspace > .review-split-detail"),
        sidebar: rect("aside.sidebar"),
        viewport: window.innerWidth,
      };
    });
    // 문서·캔버스와 목록 모두 폭을 넘지 않는다.
    expect(geometry.pageOverflow).toBeLessThanOrEqual(0);
    expect(geometry.canvasOverflow).toBeLessThanOrEqual(0);
    expect(geometry.listOverflow).toBeLessThanOrEqual(0);
    expect(geometry.list!.width / geometry.workspace!.width).toBeCloseTo(0.60, 2);
    expect(geometry.peek!.left).toBeCloseTo(geometry.list!.right, 0);
    expect(geometry.peek!.width / geometry.workspace!.width).toBeCloseTo(0.40, 2);
    expect(geometry.peek!.right).toBeLessThanOrEqual(geometry.viewport);
    // 사이드바는 고정 216px이다.
    expect(Math.round(geometry.sidebar!.width)).toBe(216);

    // 반응 대기 탭(묶음 + 둘째 묶음 + 긴 제목 없음)에서도 같은 구조다.
    await page.getByRole("tab", { name: /^반응 대기/ }).click();
    await expect(page.getByRole("table", { name: "추적 중인 사업의 변화" })).toBeVisible();
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    expect(overflow).toBeLessThanOrEqual(0);
  });
}

test("T10: 긴 한글 제목은 표에서 한 줄 말줄임하고 전체 제목을 제공한다", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 });
  await openBriefing(page, "?view=accepted");
  const title = row(page, ID[4]).locator(".briefing-row-title");
  await expect(title).toHaveText(LONG_TITLE);
  await expect(title).toHaveAttribute("title", LONG_TITLE);
  // 제목의 표시 영역은 셀 안에 있고 한 줄 말줄임을 적용한다.
  const fits = await title.evaluate((node) => {
    const box = node.getBoundingClientRect();
    const cell = node.closest("td")!.getBoundingClientRect();
    const style = getComputedStyle(node);
    return box.right <= cell.right + 1 && box.height <= parseFloat(style.lineHeight) + 1
      && style.textOverflow === "ellipsis" && node.scrollWidth > node.clientWidth;
  });
  expect(fits).toBe(true);
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(0);
});

test("T10: 서버 오류는 안정 오류 문구와 다시 시도로 보여 준다(404와 구분)", async ({ page }) => {
  await page.clock.setFixedTime(new Date(BRIEFING_NOW));
  await mockApi(page);
  await page.route("**/api/briefings/latest", (route) =>
    route.fulfill({ status: 500, contentType: "application/json", body: JSON.stringify({ error: { code: "processing_failed", message: "합성", details: null }, request_id: null }) }),
  );
  await page.goto("/briefing");
  await expect(page.getByRole("alert")).toContainText("브리핑을 불러오지 못했어요");
  await expect(page.getByRole("alert")).toContainText("processing_failed");
  await expect(page.getByRole("button", { name: "다시 시도" })).toBeVisible();
  await expect(page.getByText(NOT_FOUND)).toHaveCount(0);
});

