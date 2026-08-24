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
  onOpenNav: () => void;
  isLoading?: boolean;
}

export function TopBar({
  title,
  runs,
  selectedRunId,
  selectedRun,
  onRunChange,
  editScope,
  onOpenNav,
  isLoading = false,
}: TopBarProps) {
  return (
    <header className="topbar">
      <button className="topbar-menu" type="button" aria-label="주 메뉴 열기" onClick={onOpenNav}>
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
          <path d="M4 7h16M4 12h16M4 17h16" />
        </svg>
      </button>
      <h1>{title}</h1>
      <RunSelector
        disabled={isLoading}
        onChange={onRunChange}
        runs={runs}
        selectedRunId={selectedRunId}
      />
      <div className="topbar-spacer" />
      {editScope ? <span className="topbar-status">{editScope}</span> : null}
      <BasisPopover run={selectedRun} />
    </header>
  );
}
