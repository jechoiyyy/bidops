import { useEffect, type ReactNode } from "react";
import { Link, useLocation, useMatches } from "react-router-dom";
import type { RunSummary } from "../../lib/types";
import { BasisPopover } from "./BasisPopover";
import { RunSelector } from "./RunSelector";
import type { PageHeaderContent } from "./PageHeaderContext";
import { runSearchFor, type RouteCrumb, type RouteDataScope, type RouteTopbarMode } from "./route-meta";

/** 칸의 목적지. 목록 주소에 붙은 검색어(`?selected=`)는 유지하고 회차 선택은 목적지가 읽을 때만 붙인다. */
function crumbDestination(to: string, runSearch: string): { pathname: string; search: string } {
  const index = to.indexOf("?");
  const pathname = index === -1 ? to : to.slice(0, index);
  const own = index === -1 ? "" : to.slice(index + 1);
  const run = runSearchFor(pathname, runSearch).replace(/^\?/, "");
  const search = [own, run].filter(Boolean).join("&");
  return { pathname, search: search ? `?${search}` : "" };
}
import { preSpecReviewListUrl } from "../../lib/preSpecSelectionReview";

interface TopBarProps {
  /** 상단 경로. 마지막 `screen` 칸이 `<h1>`이 된다. 제목 모드에서는 그리지 않는다. */
  crumbs: RouteCrumb[];
  /** 상단바 표시 방식(`route-meta.ts`가 정한다). */
  topbarMode: RouteTopbarMode;
  /** 제목 모드의 `<h1>` 글자. 화면 이름 그대로다. */
  title: string;
  dataScope: RouteDataScope;
  runs: RunSummary[];
  selectedRunId: string | null;
  selectedRun: RunSummary | null;
  onRunChange: (runId: string) => void;
  runSelectorVisible: boolean;
  /** 회차 선택을 잃지 않도록 경로 링크에 그대로 넘기는 search 문자열. */
  runSearch: string;
  isLoading?: boolean;
  /** 가상회사 데모의 회사 선택기·데모 표식. demo-config가 enabled일 때만 셸이 넘긴다. */
  companyContext?: ReactNode;
  /** 화면이 올린 패널 헤더 글자(`usePageHeader`). 지금 주소의 화면 것만 온다. */
  pageHeader?: PageHeaderContent | null;
}

/** 패널 헤더의 배치. `data-header-layout`으로 CSS가 고른다. */
type HeaderLayout = "title" | "page";

/**
 * 패널 헤더(2026-11-19 최종 시안, `docs/1119_kstyle-shell/mockups/`). 흰 패널 맨 위에 붙고
 * 아래 1px 경계로 본문과 나뉜다. 별도 상단바는 없다. 어느 배치든 문서의 `<h1>`은 정확히 하나다.
 *
 * - **제목 배치**(`title`, 목록 화면 — route-meta의 제목 모드): 작은 화면 이름 · 문장형 제목
 *   `<h1>` · 한 줄 설명 / 오른쪽 액션 / 아래 탭. 화면이 `usePageHeader`로 문장을 올리기 전
 *   (로딩·오류)에는 route 이름이 `<h1>`이다.
 * - **상세 배치**(`page`, 경로 모드 route — 상세·운영 화면): 돌아갈 곳이 있으면 맨 위에 `‹ 목록`
 *   링크(`nav[aria-label="현재 위치"]`) · 화면 이름 줄과 상태 표식 · 제목 `<h1>` · 설명 · 탭.
 *   화면이 제목을 올리지 않으면 `<h1>`은 route 이름이고 화면 이름 줄은 식별자(`#501`·`notice 991`)다.
 *   옛 경로(`그룹 › 상위 › 화면 › 식별자`) 배치는 2026-11-19에 없앴다.
 *
 * 편집 범위 칩(`… 저장 가능`)은 없앴다(ADR-0066 §3.3, 시안 M4 결정 2). 담당자 이름이 인증이
 * 아니라는 안내는 이름 입력칸 옆에 그대로 있다.
 *
 * 페이지 액션은 `#page-header-actions`, 보기 탭·검색 줄은 `#page-header-tabs` portal 슬롯으로
 * 들어온다(`components/common/PageHeaderActions.tsx`). 두 슬롯은 모든 배치에서 늘 있다.
 */
export function TopBar({
  crumbs,
  topbarMode,
  title,
  dataScope,
  runs,
  selectedRunId,
  selectedRun,
  onRunChange,
  runSelectorVisible,
  runSearch,
  isLoading = false,
  companyContext = null,
  pageHeader = null,
}: TopBarProps) {
  // 오른쪽 칸은 회차 축과 (데모가 켜졌을 때만) 회사 축이다. 회차 선택기는
  // 배치와 무관하게 화면의 데이터 축이 회차일 때만 나온다.
  const contextVisible = runSelectorVisible || companyContext !== null;
  const routeLocation = useLocation();
  const matches = useMatches();
  const noticeIdParam = matches[matches.length - 1]?.params.noticeId;
  const parsedNoticeId = Number(noticeIdParam);
  const preSpecListUrl = routeLocation.pathname.startsWith("/pre-specs/")
    ? preSpecReviewListUrl(
      routeLocation.search,
      Number.isSafeInteger(parsedNoticeId) && parsedNoticeId > 0 ? parsedNoticeId : null,
    )
    : null;

  // 시안의 경로는 `상위 화면 / 레코드`다. 사이드바 1차 분류 칸은 사이드바가 이미 보여 주므로 그리지 않는다.
  const visibleCrumbs = crumbs.filter((crumb) => crumb.role !== "group");
  const layout: HeaderLayout = topbarMode === "title" ? "title" : "page";
  // 상세 배치의 돌아갈 곳: 레코드 칸 앞에서 링크를 가진 마지막 칸(사업기회 레코드는 `사업기회` 목록,
  // 입찰 변경 비교는 그 사업기회). 사전규격 상세는 목록의 필터·선택 순회를 되살리는 주소로 간다.
  const backCrumb = layout === "page"
    ? [...visibleCrumbs].reverse().find((crumb) => crumb.role !== "record" && crumb.to !== null) ?? null
    : null;
  const backTarget = backCrumb
    ? (backCrumb.context === "pre-spec-list" && preSpecListUrl ? preSpecListUrl : crumbDestination(backCrumb.to as string, runSearch))
    : null;
  const recordCrumb = visibleCrumbs.find((crumb) => crumb.role === "record") ?? null;
  const headingTitle = pageHeader?.title?.trim() || title;
  // 화면이 화면 이름 줄을 올리지 않은 상세는 식별자 칸을 그 줄로 쓴다(값을 지어내지 않는다).
  const eyebrow = pageHeader?.eyebrow ?? (layout === "page" && !pageHeader?.title ? recordCrumb?.label ?? null : null);

  // 브라우저 탭 제목. 상세는 레코드 제목, 목록(제목 배치)은 문장형 제목 대신 화면 이름을 쓴다 —
  // 여러 건을 탭으로 열어도 구분되게 한다. 화면에 이미 있는 값만 쓰고 새로 짓지 않는다.
  const screenName = visibleCrumbs[visibleCrumbs.length - 1]?.label ?? null;
  const tabName = pageHeader?.title?.trim() || (layout === "title" ? screenName : null) || title;
  useEffect(() => {
    document.title = tabName && tabName !== "BidOps Admin" ? `${tabName} · BidOps` : "BidOps Admin";
  }, [tabName]);

  return (
    <header
      className="topbar"
      data-header-layout={layout}
      data-route-data-scope={dataScope}
      data-shell-region="topbar"
      data-topbar-mode={topbarMode}
    >
      {backCrumb && backTarget ? (
        <nav aria-label="현재 위치" className="topbar-back">
          <Link className="topbar-back-link topbar-crumb-link" to={backTarget}>
            <svg aria-hidden="true" fill="none" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} viewBox="0 0 24 24"><path d="m15 6-6 6 6 6" /></svg>
            {backCrumb.label}
          </Link>
        </nav>
      ) : null}
      <div className="topbar-main">
        {(
          <div className="topbar-heading">
            {eyebrow || pageHeader?.tag ? (
              <div className="topbar-eyebrow-row">
                {eyebrow ? <p className="topbar-eyebrow" data-testid="page-header-eyebrow">{eyebrow}</p> : null}
                {pageHeader?.tag ? (
                  <span className={`bo-tag is-${pageHeader.tag.tone}`} data-testid="page-header-tag">{pageHeader.tag.label}</span>
                ) : null}
              </div>
            ) : null}
            {/* 글자만 `<h1>`에 넣는다 — 링크·칩이 들어오면 제목을 읽는 쪽이 달라진다. */}
            <h1 className="topbar-title">{headingTitle}</h1>
            {pageHeader?.description ? (
              <p className="topbar-description" data-testid="page-header-description">{pageHeader.description}</p>
            ) : null}
            {pageHeader?.facts && pageHeader.facts.length > 0 ? (
              <dl aria-label="상태 요약" className="topbar-facts" data-testid="page-header-facts">
                {pageHeader.facts.map((fact) => (
                  <div className={`topbar-fact${fact.tone ? ` is-${fact.tone}` : ""}`} data-fact={fact.key} key={fact.key}>
                    <dt>{fact.label}</dt>
                    <dd>{fact.value}</dd>
                  </div>
                ))}
              </dl>
            ) : null}
          </div>
        )}
        {/* 화면 액션 portal 슬롯. 페이지 root 밖이라 화면 CSS가 닿지 않으므로 셸이
            정렬·간격과 글자를 준다. 액션이 없는 화면에서는 칸 자체가 사라진다. */}
        <div className="topbar-page-actions" id="page-header-actions" />
        {contextVisible ? (
          <div className="topbar-context">
            {companyContext}
            {runSelectorVisible ? (
              <RunSelector
                disabled={isLoading}
                onChange={onRunChange}
                runs={runs}
                selectedRunId={selectedRunId}
              />
            ) : null}
            {runSelectorVisible ? <BasisPopover run={selectedRun} /> : null}
          </div>
        ) : null}
      </div>
      {/* 보기 탭·검색 줄 portal 슬롯(시안의 둥근 칸 탭 줄). 비어 있으면 CSS가 접는다. */}
      <div className="topbar-tabs" id="page-header-tabs" />
    </header>
  );
}
