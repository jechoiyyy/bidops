import { Link } from "react-router-dom";
import type { RunSummary } from "../../lib/types";
import { BasisPopover } from "./BasisPopover";
import { RunSelector } from "./RunSelector";
import type { RouteCrumb, RouteDataScope, RouteTopbarMode } from "./route-meta";

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
  editScope: string | null;
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
 * - **제목 모드**(`title`): 탐색과 추적 목록 4화면이다. 경로와 편집 범위 칩을
 *   빼고 화면 이름 하나만 `<h1>`으로 그린다(사용자 결정 2026-09-08). 페이지가
 *   제목 줄을 두지 않으므로 같은 이름이 세로로 두 번 나오지 않는다. 편집 범위는
 *   목록의 각 결정 UI가 이미 말하고 있어 칩을 제거해도 잃는 사실이 없다.
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
  editScope,
  runSelectorVisible,
  runSearch,
  isLoading = false,
}: TopBarProps) {
  // 제목 모드에는 편집 범위 칩이 없다. 회차 선택기는 모드와 무관하게 남는다
  // (제목 모드 화면 중에는 회차 축을 갖는 화면이 없지만, 규칙은 모드가 아니라
  // 화면의 데이터 축이 정한다).
  const contextVisible = runSelectorVisible || (topbarMode === "breadcrumb" && Boolean(editScope));
  const lastIndex = crumbs.length - 1;

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
                <CrumbLabel crumb={crumb} isLast={index === lastIndex} runSearch={runSearch} />
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
          {editScope ? (
            <span aria-label={`페이지별 편집 범위: ${editScope}`} className="topbar-status">
              {editScope}
            </span>
          ) : null}
          {runSelectorVisible ? <BasisPopover run={selectedRun} /> : null}
        </div>
      ) : null}
    </header>
  );
}

function CrumbLabel({ crumb, isLast, runSearch }: { crumb: RouteCrumb; isLast: boolean; runSearch: string }) {
  const current = isLast ? "page" as const : undefined;
  const label = crumb.to
    ? <Link className="topbar-crumb-link" to={{ pathname: crumb.to, search: runSearch }}>{crumb.label}</Link>
    : crumb.label;
  // 화면 이름 칸만 `<h1>`이다. 나머지 칸은 위치를 설명하는 보조 문구다.
  // `<h1>`의 글자는 화면 제목 그대로 남기고 상세에서는 목록 링크가 된다.
  if (crumb.role === "screen") return <h1 aria-current={current}>{label}</h1>;
  return <span aria-current={current} className="topbar-crumb-text">{label}</span>;
}
