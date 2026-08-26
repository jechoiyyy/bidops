import type { ScheduleStatus } from "../../lib/types";

export const scheduleStatuses: ScheduleStatus[] = [
  "예약",
  "실행 중",
  "성공",
  "부분 성공",
  "실패",
  "건너뜀",
];

const statusClass: Record<ScheduleStatus, string> = {
  예약: "reserved",
  "실행 중": "running",
  성공: "success",
  "부분 성공": "partial",
  실패: "failed",
  건너뜀: "skipped",
};

export function ExecutionStatus({ status }: { status: ScheduleStatus }) {
  return (
    <span className={`operations-status-badge operations-status-${statusClass[status]}`}>
      <span className="operations-status-dot" aria-hidden="true" />
      {status}
    </span>
  );
}

export function StatusLegend({ counts }: { counts: Partial<Record<ScheduleStatus, number>> }) {
  return (
    <div className="operations-status-legend" aria-label="정기 실행 상태 범례">
      {scheduleStatuses.map((status) => (
        <div className="operations-status-legend-item" key={status}>
          <ExecutionStatus status={status} />
          <span className="mono">{counts[status] ?? 0}건</span>
        </div>
      ))}
    </div>
  );
}
