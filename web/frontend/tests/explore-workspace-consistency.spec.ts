import { expect, test, type Page } from "@playwright/test";
import { mockApi } from "./api-mock";
import { mockOpportunities } from "./opportunities-fixtures";
import { mockGoNoGo } from "./go-no-go-fixtures";

/**
 * 탐색과 추적 목록 4화면(발주계획·사전규격·사업 추적·최종 Go/No-Go)의 교차 검사.
 *
 * 네 화면은 병렬로 구현됐고 각자의 spec은 자기 화면만 본다. 각 spec이 모두 통과해도
 * 상단바 제목 모드·필터 바 골격·목록 폭·머리 여백이 화면마다 조금씩 달라질 수 있다.
 * `admin-workspace-consistency.spec.ts`처럼 지원 폭 두 곳(1280×800·1440×900)에서
 * **실측**해 같은 값을 요구한다. 업무 값은 기존 fixture(`api-mock.ts` + 화면별 mock)로
 * 공급하며 운영 API에는 닿지 않는다. 업무 의미는 화면별 spec이 갖고 여기는 골격만 본다.
 *
 * 폭은 `page.setViewportSize`로 직접 준다. `playwright.config.ts`의 `LAYOUT_SPECS`에
 * 넣으면 project가 폭을 주지만 그 파일은 이 작업의 소유 밖이라, 본보기와 같은 방식으로
 * app project 안에서 두 폭을 돌린다.
 */

interface ScreenSpec {
  path: string;
  /** 상단바 `<h1>`이 그리는 화면 이름(`route-meta.ts`). */
  title: string;
  /** 필터 바 바로 아래, 목록·상세를 감싸는 면. */
  workspace: string;
  listPane: string;
  listHead: string;
  detailHead: string;
  /** 화면별 추가 mock. `mockApi` 뒤에 걸어 같은 경로만 덮어쓴다. */
  mock?: (page: Page) => Promise<unknown>;
}

const UI_SCALE = 0.9;
const physical = (logical: number) => logical * UI_SCALE;

// 방문 순서가 곧 route mock의 등록 순서다. 뒤에 등록한 handler가 이기므로
// 사업 추적 → Go/No-Go 차례로만 두 `**/api/opportunities**` mock이 겹치지 않는다.
const screens: ScreenSpec[] = [
  {
    path: "/order-plans",
    title: "발주계획",
    workspace: ".c2l-workspace",
    listPane: ".c2l-list-pane",
    listHead: ".c2l-list-head",
    detailHead: ".c2l-detail-head",
  },
  {
    path: "/pre-specs",
    title: "사전규격",
    workspace: ".pre-specs-split-workspace",
    listPane: ".pre-specs-list-pane",
    listHead: ".pre-specs-list-head",
    detailHead: ".pre-specs-detail-header",
  },
  {
    path: "/opportunities",
    title: "사업 추적",
    workspace: ".opportunity-workspace",
    listPane: ".opportunity-list-pane",
    listHead: ".opportunity-list-head",
    detailHead: ".opportunity-detail-head",
    mock: (page) => mockOpportunities(page),
  },
  {
    path: "/go-no-go",
    title: "최종 Go/No-Go",
    workspace: ".gng-workspace",
    listPane: ".gng-list-pane",
    listHead: ".gng-list-head",
    detailHead: ".gng-detail-head",
    // 조회가 느린 시나리오가 응답을 붙들고 있어도 목록·상세 골격은 그려진다.
    mock: (page) => mockGoNoGo(page, { slowMs: 60_000 }),
  },
];

interface Selectors {
  workspace: string;
  listPane: string;
  listHead: string;
  detailHead: string;
}

/** 한 화면의 골격을 브라우저 안에서 한 번에 잰다. */
function measure(selectors: Selectors) {
  const topbar = document.querySelector<HTMLElement>('header.topbar[data-topbar-mode="title"]')!;
  const heading = topbar.querySelector<HTMLElement>("h1")!;
  const slot = topbar.querySelector<HTMLElement>(".topbar-page-actions")!;
  const filters = document.querySelector<HTMLElement>(".workspace-filters")!;
  const workspace = document.querySelector<HTMLElement>(selectors.workspace)!;
  const listPane = document.querySelector<HTMLElement>(selectors.listPane)!;
  const listHead = document.querySelector<HTMLElement>(selectors.listHead)!;
  const detailHead = document.querySelector<HTMLElement>(selectors.detailHead)!;

  const topbarBox = topbar.getBoundingClientRect();
  const topbarStyle = getComputedStyle(topbar);
  const headingStyle = getComputedStyle(heading);
  const filtersStyle = getComputedStyle(filters);
  const padding = (element: Element) => {
    const style = getComputedStyle(element);
    return `${style.paddingTop} ${style.paddingRight} ${style.paddingBottom} ${style.paddingLeft}`;
  };

  return {
    titleFont: headingStyle.fontSize,
    titleWeight: headingStyle.fontWeight,
    topbarHeight: topbarBox.height,
    topbarPaddingRight: Number.parseFloat(topbarStyle.paddingRight),
    actionsGap: topbarBox.right - slot.getBoundingClientRect().right,
    crumbCount: document.querySelectorAll(".topbar-crumb").length,
    statusCount: document.querySelectorAll(".topbar-status").length,

    filtersBackground: filtersStyle.backgroundColor,
    filtersBorderBottom: filtersStyle.borderBottomWidth,
    filterEndCount: filters.querySelectorAll(":scope > .workspace-filter-line > [role='group'] + .workspace-filter-end").length,

    filtersBottom: filters.getBoundingClientRect().bottom,
    workspaceTop: workspace.getBoundingClientRect().top,
    // getBoundingClientRect() is physical after the root zoom; keep both widths
    // in that coordinate system when checking the 38% split.
    listRatio: listPane.getBoundingClientRect().width / workspace.getBoundingClientRect().width,
    listHeadPadding: padding(listHead),
    detailHeadPadding: padding(detailHead),

    rootOverflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
  };
}

test("탐색과 추적 목록 4화면은 두 지원 폭에서 같은 상단바·필터·프레임을 쓴다", async ({ page }) => {
  await mockApi(page);
  let background: string | undefined;

  for (const viewport of [{ width: 1280, height: 800 }, { width: 1440, height: 900 }]) {
    await page.setViewportSize(viewport);

    for (const screen of screens) {
      const where = `${screen.path}@${viewport.width}`;
      await screen.mock?.(page);
      await page.goto(screen.path);

      await expect(page.locator('header.topbar[data-topbar-mode="title"] h1'), `${where} 상단바 제목`)
        .toHaveText(screen.title);
      await expect(page.locator(screen.listHead), `${where} 목록 머리`).toBeVisible();
      await expect(page.locator(screen.detailHead), `${where} 상세 머리`).toBeVisible();
      await page.evaluate(() => document.fonts.ready);

      const metrics = await page.evaluate(measure, {
        workspace: screen.workspace,
        listPane: screen.listPane,
        listHead: screen.listHead,
        detailHead: screen.detailHead,
      });

      // 상단바 — 제목 하나가 화면 이름이고 경로·편집 범위 칩은 없다. 화면 액션은
      // 상단바 오른쪽 가장자리에 붙는다(떨어지는 것은 상단바 padding 만큼뿐이다).
      expect(metrics.titleFont, `${where} 제목 크기`).toBe("20px");
      expect(metrics.titleWeight, `${where} 제목 굵기`).toBe("600");
      expect(metrics.topbarHeight, `${where} 상단바 높이`).toBeCloseTo(physical(76), 0);
      expect(metrics.crumbCount, `${where} 제목 모드에는 경로 칸이 없다`).toBe(0);
      expect(metrics.statusCount, `${where} 제목 모드에는 편집 범위 칩이 없다`).toBe(0);
      expect(metrics.actionsGap, `${where} 액션이 상단바 오른쪽 끝에 붙는다`)
        .toBeLessThanOrEqual(physical(metrics.topbarPaddingRight) + 1);

      // 필터 바 — 배경이 네 화면에서 같고, 아래 workspace와 선을 두 번 그리지 않으며,
      // 첫 줄은 보기 탭 묶음 + 검색·상세 필터 칸 두 칸이다.
      background ??= metrics.filtersBackground;
      expect(metrics.filtersBackground, `${where} 필터 바 배경`).toBe(background);
      expect(metrics.filtersBorderBottom, `${where} 필터 바와 workspace 사이 선은 하나다`).toBe("0px");
      expect(metrics.filterEndCount, `${where} 보기 탭 다음의 검색·상세 필터 칸`).toBe(1);

      // 프레임 — 필터 바 아래 8px에서 workspace가 시작하고 목록은 38%다.
      expect(metrics.workspaceTop - metrics.filtersBottom, `${where} 필터 바와 workspace 사이 틈`)
        .toBeCloseTo(physical(8), 0);
      expect(metrics.listRatio, `${where} 목록 pane 비율`).toBeCloseTo(0.38, 2);
      expect(metrics.listHeadPadding, `${where} 목록 머리 여백`).toBe("8px 16px 8px 16px");
      expect(metrics.detailHeadPadding, `${where} 상세 머리 여백`).toBe("12px 16px 12px 16px");

      // 지원 폭 두 곳 모두에서 가로로 넘치지 않는다(ADR-0047).
      expect(metrics.rootOverflow, `${where} 가로 넘침`).toBeLessThanOrEqual(1);
    }
  }
});
