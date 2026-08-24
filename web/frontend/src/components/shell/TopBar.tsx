import type { RunSummary } from "../../lib/types";
import { Badge } from "../common/Badge";
import { RunSelector } from "./RunSelector";

interface TopBarProps {
  title: string;
  runs: RunSummary[];
  selectedRunId: string | null;
  selectedRun: RunSummary | null;
  onRunChange: (runId: string) => void;
  isLoading?: boolean;
}

export function TopBar({
  title,
  runs,
  selectedRunId,
  selectedRun,
  onRunChange,
  isLoading = false,
}: TopBarProps) {
  const basis = selectedRun?.screening_basis?.trim() || "미확인";
  return (
    <header className="topbar">
      <h1>{title}</h1>
      <RunSelector
        disabled={isLoading}
        onChange={onRunChange}
        runs={runs}
        selectedRunId={selectedRunId}
      />
      <Badge label={`기준선 · ${basis}`} variant="readiness" />
      <div className="topbar-spacer" />
      <span className="topbar-status">읽기 전용</span>
    </header>
  );
}
