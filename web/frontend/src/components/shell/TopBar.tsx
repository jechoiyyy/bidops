import { Link } from "react-router-dom";
import type { RunSummary } from "../../lib/types";
import { BasisPopover } from "./BasisPopover";
import { RunSelector } from "./RunSelector";
import type { RouteCrumb, RouteDataScope } from "./route-meta";

interface TopBarProps {
  /** 상단 경로. 마지막 `screen` 칸이 `<h1>`이 된다. */
  crumbs: RouteCrumb[];
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
 * 상단바는 화면 제목을 다시 쓰지 않고 **현재 위치**를 보여 준다. 각 화면의
 * `<h2>`가 시각 제목이고, 여기 `<h1>`은 접근성 랜드마크이자 경로의 한 칸이다.
 *
 * `<h1>`이 `<nav>` 안에 있는 것은 의도적이다. 제목을 두 번 쓰지 않으면서
 * 문서에 level 1 제목을 남기려면 경로의 화면 이름 칸이 그 역할을 해야 한다.
 */
export function TopBar({
  crumbs,
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
  const contextVisible = runSelectorVisible || Boolean(editScope);
  const lastIndex = crumbs.length - 1;

  return (
    <header className="topbar" data-route-data-scope={dataScope} data-shell-region="topbar">
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
