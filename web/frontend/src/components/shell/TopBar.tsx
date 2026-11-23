import { useEffect, type ReactNode } from "react";
import { Link, useLocation, useMatches } from "react-router-dom";
import { Activity, ChevronRight, ClipboardCheck, FileText, House, Layers, LayoutList, ShieldCheck, SlidersHorizontal, Target } from "lucide-react";
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

const LOCATION_ICONS = {
  대시보드: House,
  발주계획: Layers,
  사전규격: FileText,
  사업기회: Target,
  "최종 Go/No-Go": ClipboardCheck,
  "회사 근거": ShieldCheck,
  "실행 상태": Activity,
  "판정 기준": SlidersHorizontal,
};

function LocationIcon({ title }: { title: string }) {
  const Icon = LOCATION_ICONS[title as keyof typeof LOCATION_ICONS] ?? LayoutList;
  return <Icon aria-hidden="true" className="topbar-location-icon" />;
}

/** 위치와 도구는 공통 높이로 유지하고, 긴 레코드 제목은 읽기 영역에 둔다. */
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

  const visibleCrumbs = crumbs.filter((crumb) => crumb.role !== "group");
  const layout: HeaderLayout = topbarMode === "title" ? "title" : "page";
  const record = visibleCrumbs.find((crumb) => crumb.role === "record");
  const backCrumb = layout === "page"
    ? [...visibleCrumbs].reverse().find((crumb) => crumb.to !== null) ?? null
    : null;
  const backTarget = backCrumb?.to
    ? (backCrumb.context === "pre-spec-list" && preSpecListUrl ? preSpecListUrl : crumbDestination(backCrumb.to, runSearch))
    : null;
  const recordIntro = Boolean(record && pageHeader?.title);
  const matchingRoute = matches[matches.length - 1]?.params;
  const locationLabel = title === "사전규격" && matchingRoute?.noticeId
    ? `사전규격 #${matchingRoute.noticeId}`
    : title === "사업기회" && matchingRoute?.opportunityId
      ? `사업기회 #${matchingRoute.opportunityId}`
      : title;
  const tabName = pageHeader?.title?.trim() && record ? pageHeader.title : title;
  const briefDate = title === "오늘의 브리핑" ? pageHeader?.eyebrow?.split(" · ")[1] : undefined;
  useEffect(() => {
    document.title = tabName !== "BidOps Admin" ? `${tabName} · BidOps` : tabName;
  }, [tabName]);

  return (
    <header
      className="topbar"
      data-header-layout={layout}
      data-route-data-scope={dataScope}
      data-shell-region="topbar"
      data-topbar-mode={topbarMode}
    >
      <div className="topbar-main">
        {backCrumb && backTarget ? (
          <nav aria-label="현재 위치" className="topbar-back">
            <Link className="topbar-back-link topbar-crumb-link" to={backTarget}>{backCrumb.label}</Link>
            <ChevronRight aria-hidden="true" className="topbar-location-icon" />
            {recordIntro ? <span className="topbar-location-title">{locationLabel}</span> : <h1 className="topbar-location-title">{locationLabel}</h1>}
          </nav>
        ) : (
          <div className="topbar-location">
            <LocationIcon title={title} />
            {recordIntro ? <span className="topbar-location-title">{locationLabel}</span> : <h1 className="topbar-location-title">{locationLabel}</h1>}
            {briefDate ? <span className="topbar-location-date">{briefDate}</span> : null}
          </div>
        )}
        <div className="topbar-page-actions" id="page-header-actions" />
        {contextVisible ? (
          <div className="topbar-context">
            {companyContext}
            {runSelectorVisible ? (
              <>
                <RunSelector disabled={isLoading} onChange={onRunChange} runs={runs} selectedRunId={selectedRunId} />
                <BasisPopover run={selectedRun} />
              </>
            ) : null}
          </div>
        ) : null}
      </div>
      <div className="topbar-tabs" id="page-header-tabs" />
      {recordIntro ? (
        <div className="topbar-record">
          {pageHeader?.eyebrow || pageHeader?.tag ? (
            <div className="topbar-eyebrow-row">
              {pageHeader.eyebrow ? <p className="topbar-eyebrow" data-testid="page-header-eyebrow">{pageHeader.eyebrow}</p> : null}
              {pageHeader.tag ? <span className={`bo-tag is-${pageHeader.tag.tone}`} data-testid="page-header-tag">{pageHeader.tag.label}</span> : null}
            </div>
          ) : null}
          <h1 className="topbar-title">{pageHeader?.title}</h1>
          {pageHeader?.description ? <p className="topbar-description" data-testid="page-header-description">{pageHeader.description}</p> : null}
          {pageHeader?.facts?.length ? (
            <dl aria-label="상태 요약" className="topbar-facts" data-testid="page-header-facts">
              {pageHeader.facts.map((fact) => (
                <div className={`topbar-fact${fact.tone ? ` is-${fact.tone}` : ""}`} data-fact={fact.key} key={fact.key}>
                  <dt>{fact.label}</dt><dd>{fact.value}</dd>
                </div>
              ))}
            </dl>
          ) : null}
        </div>
      ) : pageHeader?.description ? <p className="topbar-description topbar-view-note" data-testid="page-header-description">{pageHeader.description}</p> : null}
    </header>
  );
}
