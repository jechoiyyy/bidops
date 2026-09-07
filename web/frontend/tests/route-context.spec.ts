import { expect, test } from "@playwright/test";
import { mockApi } from "./api-mock";

const RUN_ID = "20260817-20260823--20260824T090927.138116Z";

type RouteContextCase = {
  name: string;
  path: string;
  title: string;
  dataScope: "run" | "cumulative";
  editScope: string | null;
  runSelectorVisible: boolean;
};

const routeContexts: RouteContextCase[] = [
  { name: "dashboard", path: `/?run=${RUN_ID}`, title: "대시보드", dataScope: "run", editScope: null, runSelectorVisible: true },
  // ADR-0046 결정 7: 회차 선택기는 대시보드와 공고 판정 이력 두 화면에만 있다.
  // 검토 대기열은 회차 종속(dataScope run)이지만 선택기를 갖지 않는다 — 회차는
  // 같은 화면의 공고 판정 이력 탭에서 고르고 search로 함께 넘어간다.
  // ADR-0046 결정 3: 공고 1차 판정은 읽기 전용 이력이므로 편집 범위가 없다.
  // 같은 저장 계약은 사업 추적의 예외 작업이 갖는다.
  { name: "queue list", path: `/queue?run=${RUN_ID}`, title: "검토 대기열", dataScope: "run", editScope: null, runSelectorVisible: false },
  { name: "queue detail", path: `/queue/29?run=${RUN_ID}`, title: "검토 대기열", dataScope: "run", editScope: null, runSelectorVisible: false },
  { name: "opportunities", path: `/opportunities?run=${RUN_ID}`, title: "사업 추적", dataScope: "cumulative", editScope: "추적 상태·예외 작업 저장 가능", runSelectorVisible: false },
  { name: "bid delta", path: `/opportunities/501/bid-delta?run=${RUN_ID}`, title: "입찰 변경 비교", dataScope: "cumulative", editScope: "최종 Go/No-Go 저장 가능", runSelectorVisible: false },
  { name: "pre-specs", path: `/pre-specs?run=${RUN_ID}`, title: "사전규격", dataScope: "cumulative", editScope: null, runSelectorVisible: false },
  { name: "pre-spec detail", path: `/pre-specs/991?run=${RUN_ID}`, title: "사전규격", dataScope: "cumulative", editScope: null, runSelectorVisible: false },
  // 공고 판정 이력·담당자 리뷰 기록은 검토 대기열의 탭으로 흡수됐다(ADR-0041 결정 2).
  // 옛 경로가 리다이렉트가 아니라 각 탭의 정식 주소로 남아 있다. 공고 판정 이력만
  // 자기 화면 맥락을 갖는다 — 회차 축을 갖는 두 화면 중 하나이기 때문이다.
  { name: "judgments list", path: `/judgments?run=${RUN_ID}`, title: "공고 판정 이력", dataScope: "run", editScope: null, runSelectorVisible: true },
  { name: "judgments detail", path: `/judgments/29?run=${RUN_ID}`, title: "공고 판정 이력", dataScope: "run", editScope: null, runSelectorVisible: true },
  { name: "reviews", path: `/reviews?run=${RUN_ID}`, title: "검토 대기열", dataScope: "run", editScope: null, runSelectorVisible: false },
  // 최종 Go/No-Go는 사이드바 최상위 항목이 됐다(ADR-0041 결정 3).
  { name: "go-no-go", path: `/go-no-go?run=${RUN_ID}`, title: "최종 Go/No-Go", dataScope: "cumulative", editScope: "최종 Go/No-Go 저장 가능", runSelectorVisible: false },
  // 기준 4화면은 판정 기준 한 화면의 탭이다. 넷 다 누적 자료이므로 회차 선택기가
  // 보이지 않고, 그 사실이 1차 분류(기준과 운영)만 보고 예측된다(PRD §2.1).
  { name: "criteria", path: `/criteria?run=${RUN_ID}`, title: "판정 기준", dataScope: "cumulative", editScope: null, runSelectorVisible: false },
  { name: "profile", path: `/profile?run=${RUN_ID}`, title: "판정 기준", dataScope: "cumulative", editScope: null, runSelectorVisible: false },
  { name: "metrics", path: `/metrics?run=${RUN_ID}`, title: "판정 기준", dataScope: "cumulative", editScope: null, runSelectorVisible: false },
  { name: "quality gates", path: `/quality-gates?run=${RUN_ID}`, title: "판정 기준", dataScope: "cumulative", editScope: null, runSelectorVisible: false },
  { name: "policies", path: `/policies?run=${RUN_ID}`, title: "판정 기준", dataScope: "cumulative", editScope: null, runSelectorVisible: false },
  // 운영 3화면과 산출물 감사 로그는 실행 상태 한 화면의 탭이다.
  { name: "run-status", path: `/run-status?run=${RUN_ID}`, title: "실행 상태", dataScope: "cumulative", editScope: null, runSelectorVisible: false },
  { name: "runs", path: `/runs?run=${RUN_ID}`, title: "실행 상태", dataScope: "cumulative", editScope: null, runSelectorVisible: false },
  { name: "attachments", path: `/attachments?run=${RUN_ID}`, title: "실행 상태", dataScope: "cumulative", editScope: null, runSelectorVisible: false },
  { name: "operations", path: `/operations?run=${RUN_ID}`, title: "실행 상태", dataScope: "cumulative", editScope: null, runSelectorVisible: false },
  { name: "audit", path: `/audit?run=${RUN_ID}`, title: "실행 상태", dataScope: "cumulative", editScope: null, runSelectorVisible: false },
  { name: "deep review", path: `/deep-reviews/fixture-review?run=${RUN_ID}`, title: "심층 검토 보고서", dataScope: "cumulative", editScope: null, runSelectorVisible: false },
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

    const editScope = topbar.locator(".topbar-status");
    if (context.editScope) {
      await expect(editScope).toHaveText(context.editScope);
      await expect(editScope).toHaveAttribute("aria-label", `페이지별 편집 범위: ${context.editScope}`);
    } else {
      await expect(editScope).toHaveCount(0);
    }
  });
}

test("직접 진입한 lazy route가 metadata와 실제 화면을 함께 렌더링한다", async ({ page }) => {
  await page.goto(`/opportunities?run=${RUN_ID}`);

  const topbar = page.locator("header.topbar");
  await expect(topbar.locator("h1")).toHaveText("사업 추적");
  await expect(topbar).toHaveAttribute("data-route-data-scope", "cumulative");
  await expect(topbar.locator(".topbar-status")).toHaveText("추적 상태·예외 작업 저장 가능");
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
  await expect(topbar.locator("h1")).toHaveText("검토 대기열");
  await expect(topbar).toHaveAttribute("data-route-data-scope", "run");
  await expect(topbar.locator(".topbar-status")).toHaveCount(0);
  // 회차 선택기는 공고 판정 이력 탭에만 있다(ADR-0046 결정 7). 검토 대기열로
  // 옮겨도 회차는 주소에 그대로 남아 같은 회차를 계속 본다.
  await expect(page.getByLabel("실행 회차", { exact: true })).toHaveCount(0);
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
// 상단바는 화면 제목을 다시 쓰지 않는다. 각 화면의 `<h2>`가 시각 제목이고
// 상단바는 `그룹 › 상위 화면 › 화면 이름 › 상세 식별자`만 보여 준다.
// 화면 이름 칸이 `<h1>`이라 접근성 랜드마크는 그대로 남는다.

type BreadcrumbCase = { name: string; path: string; crumbs: string[] };

const breadcrumbCases: BreadcrumbCase[] = [
  { name: "dashboard", path: "/", crumbs: ["오늘의 업무", "대시보드"] },
  // 화면 제목이 `발주계획` 한 낱말로 바뀌었고 상단 경로도 같은 이름을 쓴다.
  { name: "order-plans", path: "/order-plans", crumbs: ["탐색과 추적", "발주계획"] },
  { name: "order-plan detail", path: "/order-plans/101", crumbs: ["탐색과 추적", "발주계획", "발주계획 C-2 상세", "#101"] },
  { name: "pre-specs", path: "/pre-specs", crumbs: ["탐색과 추적", "사전규격"] },
  { name: "pre-spec detail", path: "/pre-specs/991", crumbs: ["탐색과 추적", "사전규격", "notice 991"] },
  { name: "opportunities", path: "/opportunities", crumbs: ["탐색과 추적", "사업 추적"] },
  { name: "opportunity detail", path: "/opportunities/501", crumbs: ["탐색과 추적", "사업 추적", "#501"] },
  // 되돌릴 수 없는 결정 화면은 어느 사업기회의 결정인지 경로에 남긴다.
  { name: "bid delta", path: "/opportunities/501/bid-delta", crumbs: ["탐색과 추적", "사업 추적", "#501", "입찰 변경 비교"] },
  { name: "queue detail", path: "/queue/29", crumbs: ["탐색과 추적", "사업 추적", "검토 대기열", "공고 29"] },
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

const DETAIL_BACK_LINKS: Array<{ name: string; path: string; back: string; settles?: RegExp }> = [
  { name: "order-plan detail", path: "/order-plans/101", back: "/order-plans" },
  { name: "pre-spec detail", path: "/pre-specs/991", back: "/pre-specs" },
  { name: "opportunity detail", path: "/opportunities/501", back: "/opportunities" },
  { name: "bid delta", path: "/opportunities/501/bid-delta", back: "/opportunities" },
  // 검토 대기열·공고 판정 이력은 목록·상세가 한 화면이라, 목록 주소로 가면
  // 화면이 첫 공고를 스스로 다시 고른다(QueuePage·NoticeDetailPage의 replace
  // navigate). 링크는 목록으로 가고 그 화면이 선택을 되살리므로 착지 주소는
  // 목록이거나 목록이 되살린 선택 하나다.
  { name: "queue detail", path: "/queue/29", back: "/queue", settles: /^\/queue(?:\/\d+)?$/ },
  { name: "judgments detail", path: "/judgments/29", back: "/judgments", settles: /^\/judgments(?:\/\d+)?$/ },
  { name: "deep review", path: "/deep-reviews/fixture-review", back: "/pre-specs" },
];

for (const context of DETAIL_BACK_LINKS) {
  test(`${context.name} 상단 경로가 목록으로 돌아가는 링크를 가진다`, async ({ page }) => {
    await page.goto(`${context.path}?run=${RUN_ID}`);
    const breadcrumb = page.locator("header.topbar .topbar-breadcrumb");
    const back = breadcrumb.locator(`a[href^="${context.back}?"], a[href="${context.back}"]`);
    await expect(back).toHaveCount(1);
    // 회차 선택은 주소에만 있다. 경로 링크가 그것을 잃으면 최신 회차로 되돌아간다.
    await expect(back).toHaveAttribute("href", `${context.back}?run=${encodeURIComponent(RUN_ID)}`);
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
