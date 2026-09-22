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
 *
 * 비교 항목은 화면마다 켜고 끈다. 네 화면이 한 번에 옮겨지지 않기 때문이다 —
 * selector도 기대값도 화면이 자기 행에서 준다. 어떤 화면이 아직 자기 틀을 쓰고 있으면
 * 그 행은 공통 항목(상단바·필터 바·목록 비율·머리 여백·가로 넘침)만 갖고, 공용 골격으로
 * 옮긴 화면이 `unifiedFrame`을, 목록 pane 안쪽까지 같은 부품을 쓰는 화면이
 * `unifiedListParts`를 더 켠다. 비어 있는 항목은 "비교를 줄였다"가 아니라 "그 화면은
 * 아직 그 부품을 쓰지 않는다"는 뜻이다.
 */

interface RowTypeSpec {
  /** 목록 행의 사업명·발주기관 자리. 행의 구조가 화면마다 달라 selector도 화면이 준다. */
  title: string;
  agency: string;
  /**
   * 그 두 줄의 물리 글자 크기. 네 화면이 모두 공용 `--review-list-primary`(14.4px)를
   * 읽는다(2026-09-21 M1c 승인, 명세 §2.4). selector는 행 구조가 화면마다 달라
   * 화면이 주지만 값은 하나다.
   */
  size: string;
}

interface ScreenSpec {
  path: string;
  /** 상단바 `<h1>`이 그리는 화면 이름(`route-meta.ts`). */
  title: string;
  /** 필터 바 바로 아래, 목록·상세를 감싸는 면. */
  workspace: string;
  listPane: string;
  listHead: string;
  detailHead: string;
  /**
   * 공용 분할 골격으로 옮긴 화면 — `SplitWorkspace`·`StickyDecisionHeader`·
   * `AgencyFeature`·목록 pane 안쪽 바닥의 `ListPagerControls`를 쓴다. 발주계획·
   * 사전규격(ADR-0062)에 사업 추적이 더해졌고(시안 M1c A안), 최종 Go/No-Go는 같은
   * 골격으로 옮기는 작업이 따로 있다. 옮기기 전 화면은 이 표에서 자기 selector와
   * 자기 비교 항목만 갖는다 — 그래서 네 화면이 서로 다른 시점에 옮겨져도 이 검사는
   * 깨지지 않는다.
   */
  unifiedFrame?: boolean;
  /**
   * 목록 pane **안쪽 구성**까지 같은 부품을 쓰는 화면 — 열 이름 줄(`ListColumns`)과
   * 선택 도구줄(`SelectionToolbar`)이 있는 탐색 두 화면이다. 사업 추적은 목록을 표로
   * 두기로 했고(시안 M1c A안) 묶음 선택 작업이 없어 이 두 부품 자체가 없다.
   */
  unifiedListParts?: boolean;
  /** 목록 행 글자 단. 행 구조가 화면마다 다르므로 selector와 기대값을 화면이 준다. */
  rowType?: RowTypeSpec;
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
    unifiedFrame: true,
    unifiedListParts: true,
    rowType: { title: ".c2l-row-title", agency: ".c2l-row-agency", size: "14.4px" },
  },
  {
    path: "/pre-specs",
    title: "사전규격",
    workspace: ".pre-specs-split-workspace",
    listPane: ".pre-specs-list-pane",
    listHead: ".pre-specs-list-head",
    detailHead: ".pre-specs-detail-header",
    unifiedFrame: true,
    unifiedListParts: true,
    rowType: { title: ".pre-specs-row-title", agency: ".pre-specs-row-agency", size: "14.4px" },
  },
  {
    // 사업 추적도 공용 분할 골격으로 옮겼다(시안 M1c A안). 여기 selector가 공용
    // 클래스인 것 자체가 그 사실을 검사한다 — 화면 클래스(`.opportunity-*`)는
    // 화면별 spec이 계속 쓴다.
    path: "/opportunities",
    title: "사업 추적",
    workspace: ".review-split-workspace",
    listPane: ".review-split-list",
    listHead: ".review-list-head",
    detailHead: ".review-detail-head",
    unifiedFrame: true,
    // 목록은 Astryx `Table`을 유지하고(M1c A안) 묶음 선택이 없어 열 이름 줄·선택
    // 도구줄 부품이 없다. 행 글자 단은 아래 `rowType`이 따로 본다.
    rowType: { title: ".opportunity-row-title", agency: ".opportunity-row-agency", size: "14.4px" },
    mock: (page) => mockOpportunities(page),
  },
  {
    // 최종 Go/No-Go도 공용 분할 골격으로 옮겼다(C2). 사업 추적과 같이 selector가
    // 공용 클래스인 것 자체가 그 사실을 검사한다.
    path: "/go-no-go",
    title: "최종 Go/No-Go",
    workspace: ".review-split-workspace",
    listPane: ".review-split-list",
    listHead: ".review-list-head",
    detailHead: ".review-detail-head",
    unifiedFrame: true,
    // 목록은 Astryx `Table`을 유지하고(M1c A안) 묶음 선택이 없어 열 이름 줄·선택
    // 도구줄 부품이 없다 — `unifiedListParts`는 켜지 않는다.
    rowType: { title: ".gng-row-title", agency: ".gng-row-agency", size: "14.4px" },
    // 조회가 느린 시나리오가 응답을 붙들고 있어도 목록·상세 골격은 그려진다.
    // `slowMs`는 **선택한 사업의 상세 조회**만 붙들고 대기열은 그대로 오므로
    // 행(`.gng-row-*`)과 상세 머리는 그려진다.
    mock: (page) => mockGoNoGo(page, { slowMs: 60_000 }),
  },
];

interface Selectors {
  workspace: string;
  listPane: string;
  listHead: string;
  detailHead: string;
  rowType: { title: string; agency: string } | null;
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
    // 검색·상세 필터·회차는 탭 아래 도구 행 하나에 있고, 도구 행의 DOM 순서가
    // 키보드 순서와 같다. 사전규격의 추가 조건은 이 행에서 필요할 때만 줄바꿈한다.
    filterToolsCount: filters.querySelectorAll(":scope > .workspace-filter-tools").length,
    filterToolsBelowLine: (() => {
      const line = filters.querySelector<HTMLElement>(":scope > .workspace-filter-line");
      const tools = filters.querySelector<HTMLElement>(":scope > .workspace-filter-tools");
      return Boolean(line && tools && tools.getBoundingClientRect().top >= line.getBoundingClientRect().bottom - 1);
    })(),

    filtersBottom: filters.getBoundingClientRect().bottom,
    workspaceTop: workspace.getBoundingClientRect().top,
    // Native CSS coordinates are already the rendered coordinates.
    listRatio: listPane.getBoundingClientRect().width / workspace.getBoundingClientRect().width,
    listHeadPadding: padding(listHead),
    detailHeadPadding: padding(detailHead),

    /* 상세 머리는 공용 `StickyDecisionHeader`다 — 본문을 스크롤해도 위에 붙는다. */
    detailHeadPrimitive: detailHead.getAttribute("data-review-primitive"),
    detailHeadPosition: getComputedStyle(detailHead).position,

    /* ADR-0062 — 목록 pane 안쪽 구성. 열 이름 줄·선택 도구줄은 목록 pane 안에 있고,
       페이저는 (있을 때) **목록 pane 안쪽 바닥**이다. */
    listColumnCount: listPane.querySelectorAll('[data-review-primitive="list-columns"] > *').length,
    listColumnsPadding: (() => {
      const columns = listPane.querySelector('[data-review-primitive="list-columns"]');
      return columns ? padding(columns) : null;
    })(),
    toolbarCount: listPane.querySelectorAll('[data-review-primitive="selection-toolbar"]').length,
    /** WCAG 2.2 AA 2.5.8 — 화면 축소(`--bo-ui-scale`) 뒤의 실제 클릭 대상 높이. */
    toolbarButtonMinHeight: Math.min(
      ...[...listPane.querySelectorAll<HTMLElement>('[data-review-primitive="selection-toolbar"] button')]
        .map((button) => button.getBoundingClientRect().height),
    ),
    /** 사유 줄은 비어 있어도 높이를 지킨다(선택이 바뀔 때 목록이 밀리지 않게). */
    toolbarReasonHeight: (() => {
      const reason = listPane.querySelector<HTMLElement>(".review-selection-reason");
      return reason ? reason.getBoundingClientRect().height : null;
    })(),
    /** 페이저가 목록 pane 밖(workspace 형제)에 있으면 이 값이 0이 된다. */
    pagerInsideListPane: listPane.querySelectorAll('[data-review-primitive="list-pager"]').length,
    pagerOutsideListPane: document.querySelectorAll('[data-review-primitive="list-pager"]').length
      - listPane.querySelectorAll('[data-review-primitive="list-pager"]').length,
    /** 상세 머리의 발주기관 강조 블록. 두 화면이 같은 primitive를 쓴다. */
    agencyFeatureBackground: (() => {
      const agency = detailHead.querySelector('[data-review-primitive="agency-feature"]');
      return agency ? getComputedStyle(agency).backgroundColor : null;
    })(),
    agencyFeaturePadding: (() => {
      const agency = detailHead.querySelector('[data-review-primitive="agency-feature"]');
      return agency ? padding(agency) : null;
    })(),
    /** 목록 행의 사업명·발주기관 글자 크기. 자리는 화면이 알려 준다. */
    rowType: (() => {
      if (!selectors.rowType) return null;
      const styleOf = (selector: string) => {
        const element = listPane.querySelector<HTMLElement>(selector);
        return element ? getComputedStyle(element).fontSize : null;
      };
      return {
        title: styleOf(selectors.rowType.title),
        agency: styleOf(selectors.rowType.agency),
      };
    })(),

    rootOverflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
  };
}

test("탐색과 추적 목록 4화면은 두 지원 폭에서 같은 상단바·필터·프레임을 쓴다", async ({ page }) => {
  await mockApi(page);
  let background: string | undefined;
  let agencyBackground: string | null | undefined;

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
        rowType: screen.rowType ? { title: screen.rowType.title, agency: screen.rowType.agency } : null,
      });

      // 상단바 — 제목 하나가 화면 이름이고 경로·편집 범위 칩은 없다. 화면 액션은
      // 상단바 오른쪽 가장자리에 붙는다(떨어지는 것은 상단바 padding 만큼뿐이다).
      expect(metrics.titleFont, `${where} 제목 크기`).toBe("18px");
      expect(metrics.titleWeight, `${where} 제목 굵기`).toBe("600");
      expect(metrics.topbarHeight, `${where} 상단바 높이`).toBeCloseTo(physical(76), 0);
      expect(metrics.crumbCount, `${where} 제목 모드에는 경로 칸이 없다`).toBe(0);
      expect(metrics.statusCount, `${where} 제목 모드에는 편집 범위 칩이 없다`).toBe(0);
      expect(metrics.actionsGap, `${where} 액션이 상단바 오른쪽 끝에 붙는다`)
        .toBeLessThanOrEqual(metrics.topbarPaddingRight + 1);

      // 필터 바 — 배경이 네 화면에서 같고, 아래 workspace와 선을 두 번 그리지 않으며,
      // 첫 줄은 보기 탭이고 조회 도구는 그 아래 한 행이다.
      background ??= metrics.filtersBackground;
      expect(metrics.filtersBackground, `${where} 필터 바 배경`).toBe(background);
      expect(metrics.filtersBorderBottom, `${where} 필터 바와 workspace 사이 선은 하나다`).toBe("0px");
      expect(metrics.filterToolsCount, `${where} 보기 탭 아래 조회 도구 행`).toBe(1);
      expect(metrics.filterToolsBelowLine, `${where} 조회 도구 행이 보기 탭 아래에 놓인다`).toBe(true);

      // 프레임 — 필터 바 아래 8px에서 workspace가 시작하고 목록은 38%다.
      expect(metrics.workspaceTop - metrics.filtersBottom, `${where} 필터 바와 workspace 사이 틈`)
        .toBeCloseTo(physical(8), 0);
      expect(metrics.listRatio, `${where} 목록 pane 비율`).toBeCloseTo(0.38, 2);
      expect(metrics.listHeadPadding, `${where} 목록 머리 여백`).toBe("7.2px 14.4px 7.2px 14.4px");
      expect(metrics.detailHeadPadding, `${where} 상세 머리 여백`).toBe("10.8px 14.4px 10.8px 14.4px");

      // 공용 골격으로 옮긴 화면 — 상세 머리가 sticky 부품이고, 발주기관 강조 블록이
      // 같은 값을 쓰며, 페이저는 목록 pane 안쪽 바닥에만 있다.
      if (screen.unifiedFrame) {
        expect(metrics.detailHeadPrimitive, `${where} 상세 머리는 공용 sticky 부품이다`)
          .toBe("sticky-decision-header");
        expect(metrics.detailHeadPosition, `${where} 상세 머리는 본문 스크롤에도 위에 붙는다`)
          .toBe("sticky");
        expect(metrics.pagerOutsideListPane, `${where} 페이저는 목록 pane 밖에 없다`).toBe(0);
        // 명세 §2.2 — 한 쪽에 다 들어오는 목록에서도 페이저 줄은 남는다(공용 `ListPagerControls`).
        expect(metrics.pagerInsideListPane, `${where} 페이저 줄은 늘 목록 pane 안에 있다`).toBe(1);
        agencyBackground ??= metrics.agencyFeatureBackground;
        expect(metrics.agencyFeatureBackground, `${where} 발주기관 블록 배경`).toBe(agencyBackground);
        expect(metrics.agencyFeaturePadding, `${where} 발주기관 블록 여백`).toBe("10.8px 14.4px 10.8px 14.4px");
      }

      // 목록 pane 안쪽 구성 — 열 이름 줄·선택 도구줄을 갖는 탐색 두 화면만(ADR-0062).
      if (screen.unifiedListParts) {
        expect(metrics.listColumnCount, `${where} 열 이름 칸`).toBe(2);
        expect(metrics.listColumnsPadding, `${where} 열 이름 줄 여백`).toBe("3.6px 14.4px 3.6px 14.4px");
        expect(metrics.toolbarCount, `${where} 선택 도구줄`).toBe(1);
        // 축소 배율을 적용한 뒤에도 도구줄 단추의 클릭 대상이 24 CSS px 이상이다.
        expect(metrics.toolbarButtonMinHeight, `${where} 도구줄 단추 클릭 대상 높이`)
          .toBeGreaterThanOrEqual(24);
        expect(metrics.toolbarReasonHeight, `${where} 비활성 사유 줄 높이`).toBeGreaterThan(0);
      }

      // 목록 행의 두 줄은 화면이 선언한 글자 단을 지킨다.
      if (screen.rowType) {
        expect(metrics.rowType?.title, `${where} 목록 사업명 크기`).toBe(screen.rowType.size);
        expect(metrics.rowType?.agency, `${where} 목록 발주기관 크기`).toBe(screen.rowType.size);
      }

      // 지원 폭 두 곳 모두에서 가로로 넘치지 않는다(ADR-0047).
      expect(metrics.rootOverflow, `${where} 가로 넘침`).toBeLessThanOrEqual(1);
    }
  }
});
