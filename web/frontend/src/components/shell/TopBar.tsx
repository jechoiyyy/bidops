import type { RefObject } from "react";
import type { RunSummary } from "../../lib/types";
import { BasisPopover } from "./BasisPopover";
import { RunSelector } from "./RunSelector";

interface TopBarProps {
  title: string;
  runs: RunSummary[];
  selectedRunId: string | null;
  selectedRun: RunSummary | null;
  onRunChange: (runId: string) => void;
  editScope: string | null;
  onToggleNav: () => void;
  menuButtonRef: RefObject<HTMLButtonElement | null>;
  navOpen: boolean;
  isLoading?: boolean;
}

export function TopBar({
  title,
  runs,
  selectedRunId,
  selectedRun,
  onRunChange,
  editScope,
  onToggleNav,
  menuButtonRef,
  navOpen,
  isLoading = false,
}: TopBarProps) {
  return (
    <header className="topbar">
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
      <div className="topbar-context">
        <RunSelector
          disabled={isLoading}
          onChange={onRunChange}
          runs={runs}
          selectedRunId={selectedRunId}
        />
        {editScope ? (
          <span aria-label={`페이지별 편집 범위: ${editScope}`} className="topbar-status">
            {editScope}
          </span>
        ) : null}
        <BasisPopover run={selectedRun} />
      </div>
    </header>
  );
}
