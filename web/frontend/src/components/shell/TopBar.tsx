import type { RefObject } from "react";
import type { RunSummary } from "../../lib/types";
import { BasisPopover } from "./BasisPopover";
import { RunSelector } from "./RunSelector";
import type { RouteDataScope } from "./route-meta";

interface TopBarProps {
  title: string;
  dataScope: RouteDataScope;
  runs: RunSummary[];
  selectedRunId: string | null;
  selectedRun: RunSummary | null;
  onRunChange: (runId: string) => void;
  editScope: string | null;
  onToggleNav: () => void;
  menuButtonRef: RefObject<HTMLButtonElement | null>;
  navOpen: boolean;
  runSelectorVisible: boolean;
  isLoading?: boolean;
}

export function TopBar({
  title,
  dataScope,
  runs,
  selectedRunId,
  selectedRun,
  onRunChange,
  editScope,
  onToggleNav,
  menuButtonRef,
  navOpen,
  runSelectorVisible,
  isLoading = false,
}: TopBarProps) {
  const contextVisible = runSelectorVisible || Boolean(editScope);

  return (
    <header className="topbar" data-route-data-scope={dataScope}>
      <button
        aria-controls="primary-navigation"
        aria-expanded={navOpen}
        aria-label={navOpen ? "주 메뉴 닫기" : "주 메뉴 열기"}
        className="topbar-menu"
        ref={menuButtonRef}
        type="button"
        onClick={onToggleNav}
      >
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
          <path d="M4 7h16M4 12h16M4 17h16" />
        </svg>
      </button>
      <div className="topbar-heading">
        <h1>{title}</h1>
      </div>
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
