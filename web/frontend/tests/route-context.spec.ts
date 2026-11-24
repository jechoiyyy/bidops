import { expect, test, type Page } from "@playwright/test";
import { mockApi, visualPreSpecNotice } from "./api-mock";
import routeFixtures from "./fixtures/api.json" with { type: "json" };

const routeNotice29 = routeFixtures["/api/notices/29"];

const RUN_ID = "20260817-20260823--20260824T090927.138116Z";

type RouteContextCase = {
  name: string;
  path: string;
  title: string;
  dataScope: "run" | "cumulative";
  runSelectorVisible: boolean;
  section?: string;
};

const routeContexts: RouteContextCase[] = [
  { name: "dashboard", path: `/?run=${RUN_ID}`, title: "오늘 할 일", dataScope: "cumulative", runSelectorVisible: false },
  // `/queue`와 `/reviews`는 현재 공고 판정 이력 route metadata를 공유한다.
  // ADR-0046 결정 3의 읽기 전용·회차 선택기·편집 범위 없음 계약을 함께 검증한다.
  { name: "queue list", path: `/queue?run=${RUN_ID}`, title: "공고 판정 이력", dataScope: "run", runSelectorVisible: true },
  { name: "queue detail", path: `/queue/29?run=${RUN_ID}`, title: "공고 판정 이력", dataScope: "run", runSelectorVisible: true },
  // 사업 추적·최종 Go/No-Go 목록은 제목 모드다. 무엇을 저장할 수 있는지는 목록 안의
  // 결정 UI가 말한다(사용자 결정 2026-09-08). 같은 metadata를 쓰는 상세
  // (`/opportunities/501`)는 경로 모드지만 상단바에 칩을 두지 않는 것은 같다.
  { name: "opportunities", path: `/opportunities?run=${RUN_ID}`, title: "사업기회", dataScope: "cumulative", runSelectorVisible: false },
  { name: "opportunity detail", path: `/opportunities/501?run=${RUN_ID}`, title: "사업기회 #501", dataScope: "cumulative", runSelectorVisible: false },
  { name: "bid delta", path: `/opportunities/501/bid-delta?run=${RUN_ID}`, title: "입찰 참여 결정", dataScope: "cumulative", runSelectorVisible: false },
  { name: "pre-specs", path: `/pre-specs?run=${RUN_ID}`, title: "사전규격", dataScope: "cumulative", runSelectorVisible: false },
  { name: "pre-spec detail", path: `/pre-specs/991?run=${RUN_ID}`, title: visualPreSpecNotice.title, dataScope: "cumulative", runSelectorVisible: false },
  // 공고 판정 이력·담당자 리뷰 기록은 검토 대기열의 탭으로 흡수됐다(ADR-0041 결정 2).
  // 옛 경로가 리다이렉트가 아니라 각 탭의 정식 주소로 남아 있고, 두 회차 종속
  // 탭은 공고 판정 이력 route metadata를 공유한다.
  // 2026-11-19: `/judgments`는 입찰공고 상세로 남고 이름도 그렇게 읽힌다(사전규격 단계 수정안 §5 #6).
  { name: "judgments list", path: `/judgments?run=${RUN_ID}`, title: "입찰공고 상세", dataScope: "run", runSelectorVisible: true },
  { name: "judgments detail", path: `/judgments/29?run=${RUN_ID}`, title: "입찰공고 상세", dataScope: "run", runSelectorVisible: true },
  { name: "reviews", path: `/reviews?run=${RUN_ID}`, title: "공고 판정 이력", dataScope: "run", runSelectorVisible: true },
  // 최종 Go/No-Go는 사이드바 최상위 항목이 됐다(ADR-0041 결정 3).
  { name: "go-no-go", path: `/go-no-go?run=${RUN_ID}`, title: "최종 Go/No-Go", dataScope: "cumulative", runSelectorVisible: false },
  // 두 관리 화면은 구역과 회차 쿼리를 별도로 유지한다.
  { name: "criteria", path: `/criteria?run=${RUN_ID}`, title: "판정 기준", dataScope: "cumulative", runSelectorVisible: false, section: "선별 정책" },
  { name: "order-plan-policies", path: `/order-plan-policies?run=${RUN_ID}`, title: "판정 기준", dataScope: "cumulative", runSelectorVisible: false, section: "선별 정책" },
  { name: "profile", path: `/profile?run=${RUN_ID}`, title: "판정 기준", dataScope: "cumulative", runSelectorVisible: false, section: "판정용 프로필 사본" },
  { name: "metrics", path: `/metrics?run=${RUN_ID}`, title: "판정 기준", dataScope: "cumulative", runSelectorVisible: false, section: "공고 판정 결과 검증" },
  { name: "quality gates", path: `/quality-gates?run=${RUN_ID}`, title: "판정 기준", dataScope: "cumulative", runSelectorVisible: false, section: "품질 게이트" },
  { name: "policies", path: `/policies?run=${RUN_ID}`, title: "판정 기준", dataScope: "cumulative", runSelectorVisible: false, section: "판정 정책" },
  { name: "run-status", path: `/run-status?run=${RUN_ID}`, title: "실행 상태", dataScope: "cumulative", runSelectorVisible: false, section: "수집 실행" },
  { name: "runs", path: `/runs?run=${RUN_ID}`, title: "실행 상태", dataScope: "cumulative", runSelectorVisible: false, section: "수집 실행" },
  { name: "attachments", path: `/attachments?run=${RUN_ID}`, title: "실행 상태", dataScope: "cumulative", runSelectorVisible: false, section: "첨부 확보" },
  { name: "operations", path: `/operations?run=${RUN_ID}`, title: "실행 상태", dataScope: "cumulative", runSelectorVisible: false, section: "공고 자동 판정 일정" },
  { name: "audit", path: `/audit?run=${RUN_ID}`, title: "실행 상태", dataScope: "cumulative", runSelectorVisible: false, section: "산출물 감사 로그" },
];

test.beforeEach(async ({ page }) => {
  await mockApi(page);
});

for (const context of routeContexts) {
  test(`${context.name} route context`, async ({ page }) => {
    await page.goto(context.path);

    const topbar = page.locator("header.topbar");
    await expect(topbar.locator("h1")).toHaveText(context.title);
    await expect(topbar).toHaveAttribute("data-route-data-scope", context.dataScope);

    if (context.section) {
      const nav = page.getByRole("navigation", { name: `${context.title} 구역`, exact: true });
      await expect(nav.locator('a[aria-current="page"]')).toHaveText(context.section);
      await expect(page).toHaveURL(context.path);
    }

    const runSelector = page.getByLabel("실행 회차", { exact: true });
    if (context.runSelectorVisible) {
      await expect(runSelector).toBeVisible();
      await expect(runSelector).toHaveValue(RUN_ID);
    } else {
      await expect(runSelector).toHaveCount(0);
    }

    // 편집 범위 칩(`… 저장 가능`)은 어느 화면에도 없다(ADR-0066 §3.3, 시안 M4
    // 결정 2). 로그인·권한이 없어 모든 사용자에게 늘 같은 말을 했고, 무엇을 저장할
    // 수 있는지는 각 화면의 결정 UI가 말한다. 읽기 전용 표식과 "담당자 이름은
    // 인증이 아닙니다" 안내는 화면 안에 그대로 있다.
    await expect(topbar.locator(".topbar-status")).toHaveCount(0);
  });
}

test("직접 진입한 lazy route가 metadata와 실제 화면을 함께 렌더링한다", async ({ page }) => {
  // 경로 모드 화면(상세)에서 확인한다 — 제목·데이터 축·경로 칸이 모두 있는 쪽이다.
  await page.goto(`/opportunities/501?run=${RUN_ID}`);

  const topbar = page.locator("header.topbar");
  await expect(topbar.locator("h1")).toHaveText("사업기회 #501");
  await expect(topbar).toHaveAttribute("data-route-data-scope", "cumulative");
  await expect(topbar).toHaveAttribute("data-topbar-mode", "breadcrumb");
  await expect(topbar.locator(".topbar-status")).toHaveCount(0);
  await expect(page.getByLabel("실행 회차", { exact: true })).toHaveCount(0);
  // RL-02: 단독 상세 route는 레코드 페이지(`/opportunities/:id/activity`)로 바뀌었다.
  await expect(page).toHaveURL(/\/opportunities\/501\/activity/);
  // lazy chunk가 실제 레코드 화면을 그렸는지 본다(이 spec은 활동 응답을 mock하지 않으므로 상태 문구는 보지 않는다).
  await expect(page.getByRole("region", { name: "사업기회 레코드" })).toBeVisible();
});

test("SPA 내부 link click으로 lazy route에 들어가도 metadata와 화면이 유지된다", async ({ page }) => {
  await page.goto(`/judgments/29?run=${RUN_ID}`);
  const topbar = page.locator("header.topbar");
  // 2026-11-19: 입찰공고 상세에는 판정 대기열(`/queue`·`/reviews`)로 가는 링크·탭이 없다
  // (C-1 공고 판정 미가동, 사전규격 단계 수정안 §3 B). 상세가 그려진 뒤 확인한다.
  await expect(page.locator(".notice-read-detail .workbench-record")).toBeVisible();
  await expect(topbar.locator(".topbar-location-title")).toHaveText("입찰공고 상세");
  await expect(topbar.locator("h1")).toHaveText(routeNotice29.title);
  await expect(page.locator(".notice-read-detail").getByRole("link", { name: "검토 대기열" })).toHaveCount(0);
  await expect(page.getByRole("tab", { name: "검토 대기열" })).toHaveCount(0);
  await expect(page.getByRole("tab", { name: "담당자 리뷰 기록" })).toHaveCount(0);

  // lazy route로 가는 SPA 내부 링크(사이드바)를 눌러도 도착 화면의 metadata가 맞는다.
  await page.locator("aside.sidebar").getByRole("link", { name: "사전규격" }).click();
  await expect(topbar.locator("h1")).toHaveText("사전규격");
  await expect(topbar).toHaveAttribute("data-route-data-scope", "cumulative");
  await expect(page.locator(".pre-specs-page")).toBeVisible();
  expect(new URL(page.url()).pathname).toBe("/pre-specs");
});

// 오류 경계의 "다시 시도"가 `window.location.reload()`였다. 새로고침은 다른
// 화면에서 작성 중이던 초안까지 지우므로, 복구는 경계 state를 비우고 실패한
// 조회만 다시 묻는 것으로 끝나야 한다. 위치가 바뀌면 옛 오류는 스스로 사라진다.
test("라우트 오류 재시도는 reload 없이 복구한다", async ({ page }) => {
  await page.addInitScript(() => {
    (window as unknown as { __reloads: number }).__reloads = 0;
    const original = window.location.reload.bind(window.location);
    Object.defineProperty(window.location, "reload", {
      configurable: true,
      value: () => {
        (window as unknown as { __reloads: number }).__reloads += 1;
        return original;
      },
    });
  });
  // lazy chunk 하나만 못 가져오게 해서 오류 경계를 띄운다.
  await page.route("**/assets/GoNoGoPage-*.js", (route) => route.abort());

  await page.goto("/go-no-go");
  const boundary = page.locator(".lazy-route-error");
  await expect(boundary).toBeVisible();
  await expect(boundary).toContainText("새로고침 없이");

  // 이 표식이 살아 있으면 문서가 다시 로드되지 않았다는 뜻이다.
  await page.evaluate(() => { (window as unknown as { __sentinel: string }).__sentinel = "kept"; });
  await boundary.getByRole("button", { name: "다시 시도" }).click();

  expect(await page.evaluate(() => (window as unknown as { __sentinel?: string }).__sentinel)).toBe("kept");
  expect(await page.evaluate(() => (window as unknown as { __reloads: number }).__reloads)).toBe(0);
  expect(new URL(page.url()).pathname).toBe("/go-no-go");

  // 위치가 바뀌면 경계는 스스로 비워지고 다음 화면이 그대로 열린다.
  await page.locator("aside.sidebar").getByRole("link", { name: "오늘 할 일", exact: true }).click();
  await expect(page.locator("header.topbar h1")).toHaveText("오늘 할 일");
  await expect(page.locator(".lazy-route-error")).toHaveCount(0);
  expect(await page.evaluate(() => (window as unknown as { __reloads: number }).__reloads)).toBe(0);
});

test("누적 화면은 회차 API 실패와 무관하게 열린다", async ({ page }) => {
  let runRequestCount = 0;
  await page.route("**/api/runs**", async (route) => {
    runRequestCount += 1;
    await route.fulfill({
      status: 503,
      contentType: "application/json",
      body: JSON.stringify({ detail: "run fixture unavailable" }),
    });
  });

  await page.goto(`/opportunities?run=${RUN_ID}`);
  await expect(page.locator("header.topbar h1")).toHaveText("사업기회");
  await expect(page.getByLabel("실행 회차", { exact: true })).toHaveCount(0);
  await expect(page.locator(".opportunities-page")).toBeVisible();
  await expect(page.locator(".shell-notice")).toHaveCount(0);
  expect(runRequestCount).toBe(0);
  expect(new URL(page.url()).searchParams.get("run")).toBe(RUN_ID);
});

// ── 패널 헤더의 현재 위치 ─────────────────────────────────────────────────────
// 위치 줄은 화면명 또는 목록 복귀 링크와 레코드 위치를 표시한다. 상세 본문이
// 레코드 제목을 제공하면 제목 배치로 이어지고 패널 헤더의 `<h1>`은 하나다.
type HeaderCase = {
  name: string;
  path: string;
  back: string | null;
  location: string;
  notice?: { detail: string; identifier: string };
};

const headerCases: HeaderCase[] = [
  { name: "dashboard", path: "/", back: null, location: "오늘 할 일" },
  { name: "pre-spec detail", path: "/pre-specs/991", back: "‹ 목록", location: "사전규격 #991" },
  { name: "opportunity detail", path: "/opportunities/501", back: "사업기회", location: "사업기회 #501" },
  { name: "bid delta", path: "/opportunities/501/bid-delta", back: "#501", location: "입찰 참여 결정" },
  {
    name: "queue detail", path: "/queue/29", back: "공고 판정 이력", location: "공고 판정 이력",
    notice: { detail: ".workbench-record", identifier: ".notice-record-key" },
  },
  {
    name: "judgments detail", path: "/judgments/29", back: "입찰공고 상세", location: "입찰공고 상세",
    notice: { detail: ".workbench-record", identifier: ".notice-record-key" },
  },
  { name: "criteria", path: "/criteria", back: null, location: "판정 기준" },
  { name: "run-status", path: "/run-status", back: null, location: "실행 상태" },
];

for (const context of headerCases) {
  test(`${context.name} 패널 헤더 위치`, async ({ page }) => {
    await page.goto(context.path);
    const topbar = page.locator("header.topbar");
    await expect(topbar.locator(".topbar-breadcrumb")).toHaveCount(0);
    const back = topbar.getByRole("navigation", { name: "현재 위치" }).getByRole("link");
    if (context.back === null) await expect(back).toHaveCount(0);
    else await expect(back).toHaveText(context.back);
    await expect(topbar.locator(".topbar-main .topbar-location-title")).toHaveText(context.location);
    if (context.notice) {
      const detail = page.locator(context.notice.detail);
      await expect(topbar.getByRole("heading", { name: routeNotice29.title, exact: true })).toBeVisible();
      await expect(detail.locator(context.notice.identifier)).toHaveText(routeNotice29.notice_key);
      await expect.poll(() => new URL(page.url()).pathname).toBe(context.path);
      await expect.poll(() => new URL(page.url()).searchParams.get("run")).toBe(routeNotice29.run_id);
    }
    // 제목은 하나만 `<h1>`이다. 제목을 두 번 쓰지 않는다.
    await expect(topbar.locator("h1")).toHaveCount(1);
  });
}

// 제목 모드: 탐색과 추적 목록 4화면. 경로와 편집 범위 칩이 없고 화면 이름 하나만
// `<h1>`으로 남는다. 페이지는 제목 줄을 두지 않으므로 이 글자가 화면의 시각 제목이다.
const titleCases: Array<{ name: string; path: string; title: string }> = [
  { name: "order-plans", path: "/order-plans", title: "발주계획" },
  { name: "pre-specs", path: "/pre-specs", title: "사전규격" },
  { name: "opportunities", path: "/opportunities", title: "사업기회" },
  { name: "go-no-go", path: "/go-no-go", title: "최종 Go/No-Go" },
];

for (const context of titleCases) {
  test(`${context.name} 상단 제목 모드`, async ({ page }) => {
    await page.goto(context.path);
    const topbar = page.locator("header.topbar");
    await expect(topbar).toHaveAttribute("data-topbar-mode", "title");
    await expect(topbar.locator("h1")).toHaveText(context.title);
    await expect(topbar.locator("h1")).toHaveCount(1);
    // 경로도 편집 범위 칩도 그리지 않는다. 세로 공간을 제목에 한 번만 쓴다.
    await expect(topbar.locator(".topbar-breadcrumb")).toHaveCount(0);
    await expect(topbar.locator(".topbar-crumb")).toHaveCount(0);
    await expect(topbar.locator(".topbar-status")).toHaveCount(0);
  });
}

// 대시보드는 제목 모드가 아니다(문장형 제목을 페이지가 올린다). 액션 portal은 두 배치가 함께 쓰므로
// 이 배치에서도 슬롯이 그대로 동작하는지 같은 자리에서 확인한다.
test("대시보드는 경로 모드이면서 상단바 액션 슬롯을 그대로 쓴다", async ({ page }) => {
  await page.goto("/");
  const topbar = page.locator("header.topbar");
  await expect(topbar).toHaveAttribute("data-topbar-mode", "breadcrumb");
  await expect(topbar).toHaveAttribute("data-header-layout", "page");
  await expect(topbar.locator("#page-header-actions .dash-header-actions")).toBeVisible();
  await expect(topbar.getByRole("button", { name: "새로고침" })).toBeVisible();
});

const DETAIL_BACK_LINKS: Array<{ name: string; path: string; back: string; keepsRun: boolean; settles?: RegExp }> = [
  { name: "pre-spec detail", path: "/pre-specs/991", back: "/pre-specs", keepsRun: false },
  // 사업기회 레코드의 목록 링크는 이 사업기회를 고른 채 연다(설계고도화안 C-3).
  { name: "opportunity detail", path: "/opportunities/501", back: "/opportunities", keepsRun: false, href: "/opportunities?selected=501" },
  // 입찰 변경 비교는 한 단계 위인 그 사업기회 레코드로 돌아간다(ADR-0076, 결정 목록은 화면 안 `결정 목록으로`).
  { name: "bid delta", path: "/opportunities/501/bid-delta", back: "/opportunities/501", keepsRun: false },
  // 검토 대기열·공고 판정 이력은 목록·상세가 한 화면이라, 목록 주소로 가면
  // 화면이 첫 공고를 스스로 다시 고른다(QueuePage·NoticeDetailPage의 replace
  // navigate). 링크는 목록으로 가고 그 화면이 선택을 되살리므로 착지 주소는
  // 목록이거나 목록이 되살린 선택 하나다.
  { name: "queue detail", path: "/queue/29", back: "/queue", keepsRun: true, settles: /^\/queue(?:\/\d+)?$/ },
  { name: "judgments detail", path: "/judgments/29", back: "/judgments", keepsRun: true, settles: /^\/judgments(?:\/\d+)?$/ },
];

for (const context of DETAIL_BACK_LINKS) {
  test(`${context.name} 상단 경로가 목록으로 돌아가는 링크를 가진다`, async ({ page }) => {
    await page.goto(`${context.path}?run=${RUN_ID}`);
    // 돌아가기 링크는 패널 헤더 맨 위 `현재 위치` 링크 하나다(ADR-0076).
    const nav = page.locator("header.topbar").getByRole("navigation", { name: "현재 위치" });
    const back = nav.locator(`a[href^="${context.back}?"], a[href="${context.back}"]`);
    await expect(back).toHaveCount(1);
    // 회차 선택은 주소에만 있고, 목적지가 회차를 읽는 화면일 때만 경로 링크에
    // 그대로 남는다(route-meta.ts의 runSearchFor). `run`을 읽지 않는 화면으로
    // 돌아갈 때는 옛 회차 선택이 되살아나지 않아야 한다.
    await expect(back).toHaveAttribute(
      "href",
      "href" in context && context.href ? context.href : context.keepsRun ? `${context.back}?run=${encodeURIComponent(RUN_ID)}` : context.back,
    );
    await back.click();
    await expect.poll(() => new URL(page.url()).pathname).toMatch(context.settles ?? new RegExp(`^${context.back}$`));
  });
}

// ── PN 상세 선택 순회 context --------------------------------------------
// 목록 통합 테스트와 분리해, 저장된 opaque context가 상세 shell에서만
// 사용되고 오류·새로고침에도 임의 재구성되지 않는지만 확인한다.
const PN_REVIEW_ID = "11111111-1111-4111-8111-111111111111";
const PN_REVIEW_STORAGE_KEY = `bidops.pre-specs.review.v1.${PN_REVIEW_ID}`;
const PN_REVIEW = {
  version: 1,
  reviewId: PN_REVIEW_ID,
  orderedNoticeIds: [991, 992],
  listSearch: "sw_only=false&q=%EC%95%88%EC%A0%84&offset=200",
  filterFingerprint: "pn-route-context",
  selectionGeneration: 7,
  entryNoticeId: 991,
};

async function seedPreSpecReview(page: Page) {
  await page.addInitScript(({ key, value }) => {
    window.sessionStorage.setItem(key, JSON.stringify(value));
  }, { key: PN_REVIEW_STORAGE_KEY, value: PN_REVIEW });
}

async function mockSecondPreSpecNotice(page: Page) {
  await page.route("**/api/notices/992", async (route) => {
    if (route.request().method() !== "GET") {
      await route.fallback();
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        ...visualPreSpecNotice,
        id: 992,
        notice_key: "pre-spec:992",
        title: "두 번째 사전규격 상세",
        agency: "두 번째 발주기관",
        lifecycle: { pre_spec_no: "PRE-992" },
      }),
    });
  });
}

test("PN-02 선택 상세 navigation은 저장된 snapshot 인접 ID만 이동한다", async ({ page }) => {
  await seedPreSpecReview(page);
  await page.goto(`/pre-specs/991?${PN_REVIEW.listSearch}&selection_review=${PN_REVIEW_ID}`);

  const navigation = page.getByRole("navigation", { name: "사전규격 선택 순회" });
  await expect(navigation.locator("strong")).toHaveText("1 / 2");
  await expect(navigation.getByRole("button", { name: "이전 선택 사전규격" })).toBeDisabled();
  await expect(navigation.getByRole("button", { name: "다음 선택 사전규격" })).toBeEnabled();

  await navigation.getByRole("button", { name: "다음 선택 사전규격" }).click();
  await expect.poll(() => new URL(page.url()).pathname).toBe("/pre-specs/992");
  await expect.poll(() => new URL(page.url()).searchParams.get("selection_review")).toBe(PN_REVIEW_ID);
  await expect(navigation.locator("strong")).toHaveText("2 / 2");
  await expect(navigation.getByRole("button", { name: "다음 선택 사전규격" })).toBeDisabled();
});

test("PN-03 상세 새로고침과 오류 branch도 위치·목록 context를 보존한다", async ({ page }) => {
  await seedPreSpecReview(page);
  await page.goto(`/pre-specs/991?${PN_REVIEW.listSearch}&selection_review=${PN_REVIEW_ID}`);

  const navigation = page.getByRole("navigation", { name: "사전규격 선택 순회" });
  await expect(navigation.locator("strong")).toHaveText("1 / 2");
  await expect(page.locator(".topbar-main").getByRole("link", { name: "사전규격 목록으로" })).toHaveAttribute(
    "href",
    "/pre-specs?sw_only=false&q=%EC%95%88%EC%A0%84&offset=200",
  );

  await page.reload();
  await expect(navigation.locator("strong")).toHaveText("1 / 2");

  await navigation.getByRole("button", { name: "다음 선택 사전규격" }).click();
  await expect(navigation.locator("strong")).toHaveText("2 / 2");
  await expect(page.getByText("사전규격 992 상세를 불러오지 못했어요.")).toBeVisible();
  await expect(page.getByRole("link", { name: "사전규격 목록", exact: true })).toHaveAttribute(
    "href",
    "/pre-specs?sw_only=false&q=%EC%95%88%EC%A0%84&offset=200",
  );
});

test("PN-04 token 없는 직접 주소는 저장된 선택과 무관하게 단건 mode다", async ({ page }) => {
  await seedPreSpecReview(page);
  await page.goto(`/pre-specs/991?${PN_REVIEW.listSearch}`);

  const listUrl = `/pre-specs?${PN_REVIEW.listSearch}`;
  const topbar = page.locator("header.topbar");
  const back = topbar.locator(".topbar-main .topbar-back > a.panel-header-link:first-child");
  await expect(back).toHaveAccessibleName("사전규격 목록으로");
  await expect(back).toHaveAttribute("href", listUrl);
  await expect(topbar.getByRole("link", { name: "사전규격 목록으로" })).toHaveCount(1);
  await expect(topbar.getByRole("navigation", { name: "사전규격 선택 순회" })).toHaveCount(0);
  await back.click();
  await expect(page).toHaveURL((url) => url.pathname + url.search === listUrl);
});

test("PN-05 notice mismatch에서도 navigation shell은 위치를 잃지 않는다", async ({ page }) => {
  await seedPreSpecReview(page);
  await page.route("**/api/notices/991", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ ...visualPreSpecNotice, id: 992, source_type: "bid" }),
    });
  });
  await page.goto(`/pre-specs/991?${PN_REVIEW.listSearch}&selection_review=${PN_REVIEW_ID}`);

  const navigation = page.getByRole("navigation", { name: "사전규격 선택 순회" });
  await expect(navigation.locator("strong")).toHaveText("1 / 2");
  await expect(page.getByText("사전규격을 확인할 수 없어요")).toBeVisible();
  await expect(navigation.getByRole("button", { name: "이전 선택 사전규격" })).toBeDisabled();
  await expect(navigation.getByRole("button", { name: "다음 선택 사전규격" })).toBeEnabled();
});

test("PN-05 projection 부분 오류에서도 notice 본문과 navigation을 유지한다", async ({ page }) => {
  await seedPreSpecReview(page);
  await page.route((url) => url.pathname === "/api/pre-specs" && url.searchParams.get("notice_pk") === "991", async (route) => {
    await route.fulfill({
      status: 503,
      contentType: "application/json",
      body: JSON.stringify({ detail: "projection unavailable" }),
    });
  });
  await page.goto(`/pre-specs/991?${PN_REVIEW.listSearch}&selection_review=${PN_REVIEW_ID}`);

  const navigation = page.getByRole("navigation", { name: "사전규격 선택 순회" });
  await expect(navigation.locator("strong")).toHaveText("1 / 2");
  await expect(page.getByRole("heading", { name: "안전한 문서 준비 사전규격" })).toBeVisible();
  await expect(page.getByText("첨부 원문 취득 집계를 불러오지 못했어요")).toBeVisible();
  await expect(navigation.getByRole("button", { name: "다음 선택 사전규격" })).toBeEnabled();
});

test("PN-06 빠른 A→B 전환에서 늦은 A 응답이 B record를 덮지 않는다", async ({ page }) => {
  await seedPreSpecReview(page);
  await mockSecondPreSpecNotice(page);
  let releaseNoticeA!: () => void;
  const noticeAReady = new Promise<void>((resolve) => { releaseNoticeA = resolve; });
  await page.route("**/api/notices/991", async (route) => {
    await noticeAReady;
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(visualPreSpecNotice),
    });
  });

  await page.goto(`/pre-specs/991?${PN_REVIEW.listSearch}&selection_review=${PN_REVIEW_ID}`, {
    waitUntil: "domcontentloaded",
  });
  const navigation = page.getByRole("navigation", { name: "사전규격 선택 순회" });
  await expect(navigation.locator("strong")).toHaveText("1 / 2");
  await navigation.getByRole("button", { name: "다음 선택 사전규격" }).click();
  await expect.poll(() => new URL(page.url()).pathname).toBe("/pre-specs/992");
  await expect(page.getByRole("heading", { name: "두 번째 사전규격 상세" })).toBeVisible();
  // 2026-11-21: 기관명 강조 블록은 없어졌다. 기관은 패널 헤더 작은 줄(eyebrow)이 한 번 말하고,
  // 정보 열의 공고기관은 수요기관과 다를 때만 나온다(같은 값은 반복하지 않는다).
  await expect(page.getByTestId("page-header-eyebrow")).toHaveText("사전규격 · 두 번째 발주기관");
  await expect(page.locator("#ps-summary dt").filter({ hasText: /^공고기관$/ })).toHaveCount(0);
  await expect(page.getByText("PRE-992")).toBeVisible();

  // The old request is resolved only after the new record is mounted. Its
  // response must be ignored/aborted and never replace B's record fields.
  releaseNoticeA();
  await expect(page.getByRole("heading", { name: "두 번째 사전규격 상세" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "안전한 문서 준비 사전규격" })).toHaveCount(0);
});

test("PN-06 record key가 문서 패널 상태를 다음 항목의 기본값으로 초기화한다", async ({ page }) => {
  await seedPreSpecReview(page);
  await mockSecondPreSpecNotice(page);
  await page.goto(`/pre-specs/991?${PN_REVIEW.listSearch}&selection_review=${PN_REVIEW_ID}`);

  const panelToggle = page.getByRole("button", { name: "문서 준비 닫기", exact: true });
  await expect(panelToggle).toBeVisible();
  await panelToggle.click();
  await expect(page.getByRole("button", { name: "문서 준비 열기", exact: true })).toBeVisible();

  const navigation = page.getByRole("navigation", { name: "사전규격 선택 순회" });
  await navigation.getByRole("button", { name: "다음 선택 사전규격" }).click();
  await expect(page.getByRole("heading", { name: "두 번째 사전규격 상세" })).toBeVisible();
  // 두 번째 항목은 첫 항목에서 닫은 상태를 이어받지 않는다.
  await expect(page.getByRole("button", { name: "문서 준비 닫기", exact: true })).toBeVisible();
  await expect.poll(() => new URL(page.url()).pathname).toBe("/pre-specs/992");
  await expect(navigation.locator("strong")).toHaveText("2 / 2");
  await expect(page.locator("#page-footer").getByRole("textbox", { name: "담당자 이름 (필수)" })).toHaveCount(0);
  // 분석 전 상세는 사유 없이 추적을 시작한다. 사유가 있는 화면의 SPA 이탈 취소와
  // 초안 보존은 company-review.spec.ts의 T4 보고서 추적 결정 검사에서 확인한다.
});

// 설계고도화안 C-5: `run` 없이 연 공고 상세(사업기회 레코드·추적 흐름의 링크)는 그 공고 상세가 알려 준
// 회차를 쓰고, 기본 회차 목록(최대 500건)에 그 공고가 없어도 다른 공고로 조용히 바꾸지 않는다.
test("run 없이 연 공고 상세는 자기 회차를 쓰고 목록에 없어도 다른 공고로 바꾸지 않는다", async ({ page }) => {
  const OTHER_RUN = "20260901-20260907--20260908T090000.000000Z";
  // 그 회차는 회차 목록에도 있다(실제 공고는 적재된 회차에 속한다). 기본(최신) 회차는 아니다.
  const runs = (routeFixtures as Record<string, { items: Array<Record<string, unknown>> }>)["/api/runs"].items;
  await page.route("**/api/runs", (route) => route.fulfill({ json: {
    items: [...runs, { ...runs[0], run_id: OTHER_RUN, generated_at: "2026-08-01T00:00:00Z" }], total: runs.length + 1,
  } }));
  await page.route("**/api/notices/777", (route) => route.fulfill({ json: {
    ...(routeNotice29 as Record<string, unknown>), id: 777, run_id: OTHER_RUN, title: "기본 회차 목록에 없는 합성 공고",
  } }));
  await page.goto("/judgments/777");
  await expect(page.locator("header.topbar h1")).toHaveText("기본 회차 목록에 없는 합성 공고");
  await expect.poll(() => new URL(page.url()).pathname).toBe("/judgments/777");
  await expect.poll(() => new URL(page.url()).searchParams.get("run")).toBe(OTHER_RUN);
});

test("없는 공고 번호는 다른 공고를 보이지 않고 찾을 수 없다고 말한다", async ({ page }) => {
  await page.route("**/api/notices/888", (route) => route.fulfill({ status: 404, json: { detail: "공고를 찾을 수 없어요" } }));
  await page.goto("/judgments/888");
  await expect(page.getByText("공고 888을(를) 찾을 수 없어요.")).toBeVisible();
  await expect.poll(() => new URL(page.url()).pathname).toBe("/judgments/888");
});
