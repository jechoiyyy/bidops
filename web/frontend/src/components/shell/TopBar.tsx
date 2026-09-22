import { Link, useLocation, useMatches } from "react-router-dom";
import type { RunSummary } from "../../lib/types";
import { BasisPopover } from "./BasisPopover";
import { RunSelector } from "./RunSelector";
import { runSearchFor, type RouteCrumb, type RouteDataScope, type RouteTopbarMode } from "./route-meta";
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
}

/**
 * 상단바는 두 모드로 그린다. 어느 쪽이든 문서의 `<h1>`은 정확히 하나다.
 *
 * - **경로 모드**(`breadcrumb`, 기본): 화면 제목을 다시 쓰지 않고 **현재 위치**를
 *   보여 준다. 각 화면의 `<h2>`가 시각 제목이고, 여기 `<h1>`은 접근성 랜드마크이자
 *   경로의 한 칸이다. `<h1>`이 `<nav>` 안에 있는 것은 의도적이다 — 제목을 두 번
 *   쓰지 않으면서 문서에 level 1 제목을 남기려면 경로의 화면 이름 칸이 그 역할을
 *   해야 한다. 상세 화면은 목록으로 돌아갈 링크가 필요하므로 늘 이 모드다.
 * - **제목 모드**(`title`): 탐색과 추적 목록 4화면이다. 경로를 빼고 화면 이름
 *   하나만 `<h1>`으로 그린다(사용자 결정 2026-09-08). 페이지가 제목 줄을 두지
 *   않으므로 같은 이름이 세로로 두 번 나오지 않는다.
 *
 * 편집 범위 칩(`… 저장 가능`)은 두 모드 모두에서 없앴다(ADR-0066 §3.3, 시안 M4
 * 결정 2). 로그인·권한이 없어 이 칩은 모든 사용자에게 늘 같은 말을 했고, 무엇을
 * 저장할 수 있는지는 각 화면의 결정 UI가 이미 말한다. 읽기 전용이라는 사실을
 * 말해야 하는 화면(대시보드의 `읽기 전용`, 회사 프로필)은 화면 안에서 그대로
 * 말한다. 담당자 이름이 인증이 아니라는 안내도 이름 입력칸 옆에 그대로 있다.
 *
 * 페이지 액션은 두 모드 모두 `#page-header-actions` portal 슬롯으로 들어온다
 * (`components/common/PageHeaderActions.tsx`).
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
}: TopBarProps) {
  // 상단바 오른쪽 칸에 남은 것은 회차 축뿐이다. 회차 선택기는 모드와 무관하게
  // 화면의 데이터 축이 회차일 때만 나온다.
  const contextVisible = runSelectorVisible;
  const lastIndex = crumbs.length - 1;
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

  return (
    <header className="topbar" data-route-data-scope={dataScope} data-shell-region="topbar" data-topbar-mode={topbarMode}>
      {topbarMode === "title" ? (
        /* 글자만 넣는다. 링크·칩이 들어오면 제목을 읽는 쪽이 달라진다. */
        <h1 className="topbar-title">{title}</h1>
      ) : (
        <nav aria-label="현재 위치" className="topbar-breadcrumb">
          <ol>
            {crumbs.map((crumb, index) => (
              /* 구분자 `›`는 CSS ::before가 그린다. DOM에 넣으면 화면 이름 칸의
                 `<h1>` 글자에 섞여 제목을 읽는 쪽이 달라진다. */
              <li className={`topbar-crumb is-${crumb.role}`} key={`${crumb.role}-${crumb.label}`}>
                <CrumbLabel
                  crumb={crumb}
                  isLast={index === lastIndex}
                  preSpecListUrl={preSpecListUrl}
                  runSearch={runSearch}
                />
              </li>
            ))}
          </ol>
        </nav>
      )}
      {/* 화면 액션 portal 슬롯. 페이지 헤더를 하나 더 두지 않고도 상단바에 액션을
          넣는 자리다. `display:contents`가 아니라 실제 flex 칸이라 셸이 정렬·간격과
          4단 글자를 준다(portal 내용은 페이지 root 밖이라 화면 CSS가 닿지 않는다). */}
      <div className="topbar-page-actions" id="page-header-actions" />
      {contextVisible ? (
        <div className="topbar-context">
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
    </header>
  );
}

function CrumbLabel({
  crumb,
  isLast,
  preSpecListUrl,
  runSearch,
}: {
  crumb: RouteCrumb;
  isLast: boolean;
  preSpecListUrl: string | null;
  runSearch: string;
}) {
  const current = isLast ? "page" as const : undefined;
  const destination = crumb.context === "pre-spec-list" && preSpecListUrl
    ? preSpecListUrl
    : crumb.to
      ? { pathname: crumb.to, search: runSearchFor(crumb.to, runSearch) }
      : null;
  const label = crumb.to
    ? <Link className="topbar-crumb-link" to={destination!}>{crumb.label}</Link>
    : crumb.label;
  // 화면 이름 칸만 `<h1>`이다. 나머지 칸은 위치를 설명하는 보조 문구다.
  // `<h1>`의 글자는 화면 제목 그대로 남기고 상세에서는 목록 링크가 된다.
  if (crumb.role === "screen") return <h1 aria-current={current}>{label}</h1>;
  return <span aria-current={current} className="topbar-crumb-text">{label}</span>;
}
