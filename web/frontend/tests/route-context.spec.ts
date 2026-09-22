import { expect, test, type Page } from "@playwright/test";
import { mockApi, visualPreSpecNotice } from "./api-mock";

const RUN_ID = "20260817-20260823--20260824T090927.138116Z";

type RouteContextCase = {
  name: string;
  path: string;
  title: string;
  dataScope: "run" | "cumulative";
  runSelectorVisible: boolean;
};

const routeContexts: RouteContextCase[] = [
  { name: "dashboard", path: `/?run=${RUN_ID}`, title: "대시보드", dataScope: "cumulative", runSelectorVisible: false },
  // `/queue`와 `/reviews`는 현재 공고 판정 이력 route metadata를 공유한다.
  // ADR-0046 결정 3의 읽기 전용·회차 선택기·편집 범위 없음 계약을 함께 검증한다.
  { name: "queue list", path: `/queue?run=${RUN_ID}`, title: "공고 판정 이력", dataScope: "run", runSelectorVisible: true },
  { name: "queue detail", path: `/queue/29?run=${RUN_ID}`, title: "공고 판정 이력", dataScope: "run", runSelectorVisible: true },
  // 사업 추적·최종 Go/No-Go 목록은 제목 모드다. 무엇을 저장할 수 있는지는 목록 안의
  // 결정 UI가 말한다(사용자 결정 2026-09-08). 같은 metadata를 쓰는 상세
  // (`/opportunities/501`)는 경로 모드지만 상단바에 칩을 두지 않는 것은 같다.
  { name: "opportunities", path: `/opportunities?run=${RUN_ID}`, title: "사업 추적", dataScope: "cumulative", runSelectorVisible: false },
  { name: "opportunity detail", path: `/opportunities/501?run=${RUN_ID}`, title: "사업 추적", dataScope: "cumulative", runSelectorVisible: false },
  { name: "bid delta", path: `/opportunities/501/bid-delta?run=${RUN_ID}`, title: "입찰 변경 비교", dataScope: "cumulative", runSelectorVisible: false },
  { name: "pre-specs", path: `/pre-specs?run=${RUN_ID}`, title: "사전규격", dataScope: "cumulative", runSelectorVisible: false },
  { name: "pre-spec detail", path: `/pre-specs/991?run=${RUN_ID}`, title: "사전규격", dataScope: "cumulative", runSelectorVisible: false },
  // 공고 판정 이력·담당자 리뷰 기록은 검토 대기열의 탭으로 흡수됐다(ADR-0041 결정 2).
  // 옛 경로가 리다이렉트가 아니라 각 탭의 정식 주소로 남아 있고, 두 회차 종속
  // 탭은 공고 판정 이력 route metadata를 공유한다.
  { name: "judgments list", path: `/judgments?run=${RUN_ID}`, title: "공고 판정 이력", dataScope: "run", runSelectorVisible: true },
  { name: "judgments detail", path: `/judgments/29?run=${RUN_ID}`, title: "공고 판정 이력", dataScope: "run", runSelectorVisible: true },
  { name: "reviews", path: `/reviews?run=${RUN_ID}`, title: "공고 판정 이력", dataScope: "run", runSelectorVisible: true },
  // 최종 Go/No-Go는 사이드바 최상위 항목이 됐다(ADR-0041 결정 3).
  { name: "go-no-go", path: `/go-no-go?run=${RUN_ID}`, title: "최종 Go/No-Go", dataScope: "cumulative", runSelectorVisible: false },
  // 기준 4화면은 판정 기준 한 화면의 탭이다. 넷 다 누적 자료이므로 회차 선택기가
  // 보이지 않고, 그 사실이 1차 분류(기준과 운영)만 보고 예측된다(PRD §2.1).
  { name: "criteria", path: `/criteria?run=${RUN_ID}`, title: "판정 기준", dataScope: "cumulative", runSelectorVisible: false },
  { name: "profile", path: `/profile?run=${RUN_ID}`, title: "판정 기준", dataScope: "cumulative", runSelectorVisible: false },
  { name: "metrics", path: `/metrics?run=${RUN_ID}`, title: "판정 기준", dataScope: "cumulative", runSelectorVisible: false },
  { name: "quality gates", path: `/quality-gates?run=${RUN_ID}`, title: "판정 기준", dataScope: "cumulative", runSelectorVisible: false },
  { name: "policies", path: `/policies?run=${RUN_ID}`, title: "판정 기준", dataScope: "cumulative", runSelectorVisible: false },
  // 운영 3화면과 산출물 감사 로그는 실행 상태 한 화면의 탭이다.
  { name: "run-status", path: `/run-status?run=${RUN_ID}`, title: "실행 상태", dataScope: "cumulative", runSelectorVisible: false },
  { name: "runs", path: `/runs?run=${RUN_ID}`, title: "실행 상태", dataScope: "cumulative", runSelectorVisible: false },
  { name: "attachments", path: `/attachments?run=${RUN_ID}`, title: "실행 상태", dataScope: "cumulative", runSelectorVisible: false },
  { name: "operations", path: `/operations?run=${RUN_ID}`, title: "실행 상태", dataScope: "cumulative", runSelectorVisible: false },
  { name: "audit", path: `/audit?run=${RUN_ID}`, title: "실행 상태", dataScope: "cumulative", runSelectorVisible: false },
  { name: "deep review", path: `/deep-reviews/fixture-review?run=${RUN_ID}`, title: "심층 검토 보고서", dataScope: "cumulative", runSelectorVisible: false },
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
  await expect(topbar.locator("h1")).toHaveText("사업 추적");
  await expect(topbar).toHaveAttribute("data-route-data-scope", "cumulative");
  await expect(topbar).toHaveAttribute("data-topbar-mode", "breadcrumb");
  await expect(topbar.locator(".topbar-status")).toHaveCount(0);
  await expect(page.getByLabel("실행 회차", { exact: true })).toHaveCount(0);
  await expect(page.locator(".opportunities-page")).toBeVisible();
});

test("SPA 내부 link click으로 lazy route에 들어가도 metadata와 화면이 유지된다", async ({ page }) => {
  await page.goto(`/judgments/29?run=${RUN_ID}`);
  // 판정 화면과 사이드바가 같은 이름의 링크를 갖는다. 이름만으로 고르면 lazy
  // chunk가 그려지기 전에는 하나, 그려진 뒤에는 둘이 잡혀 strict mode를 어긴다.
  // 통과하던 실행은 출발 화면이 아직 안 그려진 상태를 눌렀다는 뜻이므로,
  // 화면이 그려진 것을 확인한 뒤 그 화면의 링크로 이동한다. 사이드바는 좁은
  // 폭에서 접히므로 지원 폭 어디에서나 같은 동작을 하는 쪽은 화면 안의 링크다.
  const toQueue = page.locator(".judgment-page-actions").getByRole("link", { name: "검토 대기열" });
  await expect(toQueue).toBeVisible();
  await toQueue.click();

  const topbar = page.locator("header.topbar");
  await expect(topbar.locator("h1")).toHaveText("공고 판정 이력");
  await expect(topbar).toHaveAttribute("data-route-data-scope", "run");
  await expect(topbar.locator(".topbar-status")).toHaveCount(0);
  // `/queue` 주소도 같은 route metadata를 사용하므로 선택한 회차가 유지된다.
  await expect(page.getByLabel("실행 회차", { exact: true })).toHaveValue(RUN_ID);
  await expect(page.locator(".ws-run-note")).toContainText("공고 판정 이력");
  await expect(page.locator(".queue-page")).toBeVisible();
  expect(new URL(page.url()).searchParams.get("run")).toBe(RUN_ID);
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
  await page.locator("aside.sidebar").getByRole("link", { name: "대시보드", exact: true }).click();
  await expect(page.locator("header.topbar h1")).toHaveText("대시보드");
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
  await expect(page.locator("header.topbar h1")).toHaveText("사업 추적");
  await expect(page.getByLabel("실행 회차", { exact: true })).toHaveCount(0);
  await expect(page.locator(".opportunities-page")).toBeVisible();
  await expect(page.locator(".shell-notice")).toHaveCount(0);
  expect(runRequestCount).toBe(0);
  expect(new URL(page.url()).searchParams.get("run")).toBe(RUN_ID);
});

// ── 상단 경로(현재 위치) ────────────────────────────────────────────────────
// 경로 모드의 상단바는 화면 제목을 다시 쓰지 않는다. 각 화면의 `<h2>`가 시각
// 제목이고 상단바는 `그룹 › 상위 화면 › 화면 이름 › 상세 식별자`만 보여 준다.
// 화면 이름 칸이 `<h1>`이라 접근성 랜드마크는 그대로 남는다.
// 탐색과 추적 목록 4화면은 제목 모드로 빠졌다(아래 `titleCases`).

type BreadcrumbCase = { name: string; path: string; crumbs: string[] };

const breadcrumbCases: BreadcrumbCase[] = [
  { name: "dashboard", path: "/", crumbs: ["오늘의 업무", "대시보드"] },
  { name: "pre-spec detail", path: "/pre-specs/991", crumbs: ["탐색과 추적", "사전규격", "notice 991"] },
  { name: "opportunity detail", path: "/opportunities/501", crumbs: ["탐색과 추적", "사업 추적", "#501"] },
  // 되돌릴 수 없는 결정 화면은 어느 사업기회의 결정인지 경로에 남긴다.
  { name: "bid delta", path: "/opportunities/501/bid-delta", crumbs: ["탐색과 추적", "사업 추적", "#501", "입찰 변경 비교"] },
  { name: "queue detail", path: "/queue/29", crumbs: ["탐색과 추적", "사업 추적", "공고 판정 이력", "공고 29"] },
  { name: "judgments detail", path: "/judgments/29", crumbs: ["탐색과 추적", "사업 추적", "공고 판정 이력", "공고 29"] },
  // 심층 검토 보고서는 사전규격이 여는 화면이다(ADR-0049의 자동 시작 진입점도 거기다).
  { name: "deep review", path: "/deep-reviews/fixture-review", crumbs: ["탐색과 추적", "사전규격", "심층 검토 보고서", "fixture-…"] },
  { name: "criteria", path: "/criteria", crumbs: ["기준과 운영", "판정 기준"] },
  { name: "run-status", path: "/run-status", crumbs: ["기준과 운영", "실행 상태"] },
];

for (const context of breadcrumbCases) {
  test(`${context.name} 상단 경로`, async ({ page }) => {
    await page.goto(context.path);
    const crumbs = page.locator("header.topbar .topbar-breadcrumb .topbar-crumb");
    await expect(crumbs).toHaveText(context.crumbs);
    // 화면 이름 칸 하나만 `<h1>`이다. 제목을 두 번 쓰지 않는다.
    await expect(page.locator("header.topbar h1")).toHaveCount(1);
  });
}

// 제목 모드: 탐색과 추적 목록 4화면. 경로와 편집 범위 칩이 없고 화면 이름 하나만
// `<h1>`으로 남는다. 페이지는 제목 줄을 두지 않으므로 이 글자가 화면의 시각 제목이다.
const titleCases: Array<{ name: string; path: string; title: string }> = [
  { name: "order-plans", path: "/order-plans", title: "발주계획" },
  { name: "pre-specs", path: "/pre-specs", title: "사전규격" },
  { name: "opportunities", path: "/opportunities", title: "사업 추적" },
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

// 대시보드는 제목 모드가 아니다. 액션 portal은 두 모드가 함께 쓰므로, 경로 모드
// 화면에서도 슬롯이 그대로 동작하는지 같은 자리에서 확인한다.
test("대시보드는 경로 모드이면서 상단바 액션 슬롯을 그대로 쓴다", async ({ page }) => {
  await page.goto("/");
  const topbar = page.locator("header.topbar");
  await expect(topbar).toHaveAttribute("data-topbar-mode", "breadcrumb");
  await expect(topbar.locator(".topbar-breadcrumb")).toHaveCount(1);
  await expect(topbar.locator("#page-header-actions .dash-header-actions")).toBeVisible();
  await expect(topbar.getByRole("button", { name: "새로고침" })).toBeVisible();
});

const DETAIL_BACK_LINKS: Array<{ name: string; path: string; back: string; keepsRun: boolean; settles?: RegExp }> = [
  { name: "pre-spec detail", path: "/pre-specs/991", back: "/pre-specs", keepsRun: false },
  { name: "opportunity detail", path: "/opportunities/501", back: "/opportunities", keepsRun: false },
  { name: "bid delta", path: "/opportunities/501/bid-delta", back: "/opportunities", keepsRun: false },
  // 검토 대기열·공고 판정 이력은 목록·상세가 한 화면이라, 목록 주소로 가면
  // 화면이 첫 공고를 스스로 다시 고른다(QueuePage·NoticeDetailPage의 replace
  // navigate). 링크는 목록으로 가고 그 화면이 선택을 되살리므로 착지 주소는
  // 목록이거나 목록이 되살린 선택 하나다.
  { name: "queue detail", path: "/queue/29", back: "/queue", keepsRun: true, settles: /^\/queue(?:\/\d+)?$/ },
  { name: "judgments detail", path: "/judgments/29", back: "/judgments", keepsRun: true, settles: /^\/judgments(?:\/\d+)?$/ },
  { name: "deep review", path: "/deep-reviews/fixture-review", back: "/pre-specs", keepsRun: false },
];

for (const context of DETAIL_BACK_LINKS) {
  test(`${context.name} 상단 경로가 목록으로 돌아가는 링크를 가진다`, async ({ page }) => {
    await page.goto(`${context.path}?run=${RUN_ID}`);
    const breadcrumb = page.locator("header.topbar .topbar-breadcrumb");
    const back = breadcrumb.locator(`a[href^="${context.back}?"], a[href="${context.back}"]`);
    await expect(back).toHaveCount(1);
    // 회차 선택은 주소에만 있고, 목적지가 회차를 읽는 화면일 때만 경로 링크에
    // 그대로 남는다(route-meta.ts의 runSearchFor). `run`을 읽지 않는 화면으로
    // 돌아갈 때는 옛 회차 선택이 되살아나지 않아야 한다.
    await expect(back).toHaveAttribute(
      "href",
      context.keepsRun ? `${context.back}?run=${encodeURIComponent(RUN_ID)}` : context.back,
    );
    await back.click();
    await expect.poll(() => new URL(page.url()).pathname).toMatch(context.settles ?? new RegExp(`^${context.back}$`));
  });
}

// 심층 검토 보고서는 사전규격 아래에 둔다. 사업 추적 상세에서도 열 수 있지만
// 그때는 주소의 `from`이 그 사실을 남긴다.
test("심층 검토 보고서에서 사이드바의 사전규격 항목이 활성이다", async ({ page }) => {
  await page.goto("/deep-reviews/fixture-review");
  const active = page.locator("aside.sidebar .sidebar-item.is-active");
  await expect(active).toHaveCount(1);
  await expect(active).toHaveText("사전규격");
  await expect(active).toHaveAttribute("aria-current", "page");
});

test("사업 추적에서 연 심층 검토 보고서는 사업 추적 아래로 보인다", async ({ page }) => {
  await page.goto("/deep-reviews/fixture-review?from=opportunities");
  const active = page.locator("aside.sidebar .sidebar-item.is-active");
  await expect(active).toHaveCount(1);
  await expect(active).toHaveText("사업 추적");
  await expect(page.locator("header.topbar .topbar-crumb")).toHaveText([
    "탐색과 추적",
    "사업 추적",
    "심층 검토 보고서",
    "fixture-…",
  ]);
});

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
  await expect(page.locator(".ps-record-list-link")).toHaveAttribute(
    "href",
    "/pre-specs?sw_only=false&q=%EC%95%88%EC%A0%84&offset=200",
  );
  await expect(page.locator("header.topbar .topbar-crumb-link[href^='/pre-specs']")).toHaveAttribute(
    "href",
    "/pre-specs?sw_only=false&q=%EC%95%88%EC%A0%84&offset=200",
  );

  await page.reload();
  await expect(navigation.locator("strong")).toHaveText("1 / 2");
  await expect(page.locator(".ps-record-list-link")).toHaveAttribute(
    "href",
    "/pre-specs?sw_only=false&q=%EC%95%88%EC%A0%84&offset=200",
  );

  await navigation.getByRole("button", { name: "다음 선택 사전규격" }).click();
  await expect(navigation.locator("strong")).toHaveText("2 / 2");
  await expect(page.getByText("사전규격 992 상세를 불러오지 못했습니다.")).toBeVisible();
  await expect(page.getByRole("link", { name: "사전규격 목록", exact: true })).toHaveAttribute(
    "href",
    "/pre-specs?sw_only=false&q=%EC%95%88%EC%A0%84&offset=200",
  );
});

test("PN-04 token 없는 직접 주소는 저장된 선택과 무관하게 단건 mode다", async ({ page }) => {
  await seedPreSpecReview(page);
  await page.goto(`/pre-specs/991?${PN_REVIEW.listSearch}`);

  const navigation = page.getByRole("navigation", { name: "사전규격 선택 순회" });
  await expect(navigation.locator("strong")).toHaveText("단건 상세");
  await expect(navigation.getByRole("button", { name: "이전 선택 사전규격" })).toBeDisabled();
  await expect(navigation.getByRole("button", { name: "다음 선택 사전규격" })).toBeDisabled();
  await expect(page.locator(".ps-record-list-link")).toHaveAttribute(
    "href",
    "/pre-specs?sw_only=false&q=%EC%95%88%EC%A0%84&offset=200",
  );
  await expect(page.locator("header.topbar .topbar-crumb-link[href^='/pre-specs']")).toHaveAttribute(
    "href",
    "/pre-specs?sw_only=false&q=%EC%95%88%EC%A0%84&offset=200",
  );
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
  await expect(page.getByText("사전규격을 확인할 수 없습니다.")).toBeVisible();
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
  await expect(page.getByText("첨부 원문 취득 집계를 불러오지 못했습니다.")).toBeVisible();
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
  // ADR-0062 ⓑ — 전체 상세는 머리 최상단의 강조 블록과 식별 줄에서 기관명을 두 번
  // 보인다(사용자가 중복 표시를 확인하고 승인). 어느 자리인지 밝혀 센다.
  await expect(page.locator(".ps-record-agency-feature .review-agency-name")).toHaveText("두 번째 발주기관");
  await expect(page.locator(".ps-record-agency")).toHaveText("두 번째 발주기관");
  await expect(page.getByText("PRE-992")).toBeVisible();

  // The old request is resolved only after the new record is mounted. Its
  // response must be ignored/aborted and never replace B's record fields.
  releaseNoticeA();
  await expect(page.getByRole("heading", { name: "두 번째 사전규격 상세" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "안전한 문서 준비 사전규격" })).toHaveCount(0);
});

test("PN-06 record key가 문서 패널 상태를 초기화하고 guard 취소는 A를 보존한다", async ({ page }) => {
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
  // B's keyed body uses its own default (no stale closed override from A).
  await expect(page.getByRole("button", { name: "문서 준비 닫기", exact: true })).toBeVisible();

  // 992 has a mutable tracking form. Moving back while it is dirty opens the
  // existing child SPA guard; cancelling leaves B, its values, and context.
  const reason = page.getByRole("combobox", { name: "선택 사유" });
  await reason.click();
  await page.getByRole("option", { name: "후속 입찰공고 확인" }).click();
  const actor = page.getByRole("textbox", { name: "담당자 이름 (필수)" });
  await actor.fill("PN-06 담당자");
  await navigation.getByRole("button", { name: "이전 선택 사전규격" }).click();

  const guard = page.getByRole("alertdialog");
  await expect(guard).toBeVisible();
  await expect(guard).toContainText("저장하지 않은 추적 결정 사유와 담당자 이름이 있습니다.");
  await guard.getByRole("button", { name: "계속 편집", exact: true }).click();
  await expect(guard).toHaveCount(0);
  await expect.poll(() => new URL(page.url()).pathname).toBe("/pre-specs/992");
  await expect(reason).toContainText("후속 입찰공고 확인");
  await expect(actor).toHaveValue("PN-06 담당자");
  await expect(navigation.locator("strong")).toHaveText("2 / 2");
});
