import type { RunSummary } from "../../lib/types";
import { formatRunRangeCompact, runStatusLabel } from "../../lib/format";

interface RunSelectorProps {
  runs: RunSummary[];
  selectedRunId: string | null;
  onChange: (runId: string) => void;
  disabled?: boolean;
}

export function RunSelector({ runs, selectedRunId, onChange, disabled = false }: RunSelectorProps) {
  return (
    <label className="run-selector">
      <span className="run-selector-label">실행 회차</span>
      <select
        aria-label="실행 회차"
        disabled={disabled || runs.length === 0}
        value={selectedRunId ?? ""}
        onChange={(event) => onChange(event.target.value)}
      >
        {runs.length === 0 ? <option value="">회차 없음</option> : null}
        {runs.map((run) => (
          <option key={run.run_id} value={run.run_id}>
            {`${formatRunRangeCompact(run.run_id, run.window_from, run.window_to)} · ${runStatusLabel(run.status)}`}
          </option>
        ))}
      </select>
      <svg className="select-chevron" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
        <path d="m6 9 6 6 6-6" />
      </svg>
    </label>
  );
}
