import { formatNumber } from "../../lib/format";
import type { ScheduleExecutionSummary, ScheduleStatus } from "../../lib/types";
import { ExecutionStatus, StatusLegend } from "./ExecutionStatus";

interface ScheduleExecutionTableProps {
  items: ScheduleExecutionSummary[];
  onRecover: (item: ScheduleExecutionSummary) => void;
}

const recoverableStatuses: ScheduleStatus[] = ["실패", "부분 성공", "건너뜀"];

function triggerLabel(trigger: ScheduleExecutionSummary["trigger"]): string {
  return trigger === "manual" ? "수동" : "예약";
}

function reasonLabel(item: ScheduleExecutionSummary): string {
  if (item.skip_reason) return `건너뜀 사유 · ${item.skip_reason}`;
  if (item.failure_reason) return `실패 사유 · ${item.failure_reason}`;
  if (item.status === "부분 성공" && item.partial_artifact) return "부분 산출물 기록됨";
  return "사유 없음";
}

export function ScheduleExecutionTable({ items, onRecover }: ScheduleExecutionTableProps) {
  const counts = items.reduce<Partial<Record<ScheduleStatus, number>>>((result, item) => {
    result[item.status] = (result[item.status] ?? 0) + 1;
    return result;
  }, {});

  return (
    <section className="operations-panel operations-history-panel" aria-labelledby="operations-history-title">
      <div className="operations-panel-heading"><div><span className="operations-eyebrow">예약·catch-up·감사</span><h3 id="operations-history-title">정기 실행 이력</h3></div><span className="operations-panel-note">{items.length}건</span></div>
      <div className="operations-panel-body operations-history-body">
        <StatusLegend counts={counts} />
        {items.length === 0 ? <p className="operations-empty-value" role="status">아직 예약·catch-up·실행 이력이 없습니다.</p> : (
          <div className="operations-table-scroll">
            <table className="operations-history-table">
              <caption className="operations-visually-hidden">정기 실행 상태와 기간, 실행 결과, 실패·건너뜀 사유</caption>
              <thead><tr><th scope="col">상태</th><th scope="col">기간 · 종류</th><th scope="col">트리거</th><th scope="col">실행·파생 링크</th><th scope="col">건수</th><th scope="col">사유</th><th scope="col"><span className="operations-visually-hidden">복구</span></th></tr></thead>
              <tbody>
                {items.map((item) => {
                  const recoverable = recoverableStatuses.includes(item.status);
                  return (
                    <tr key={item.execution_id}>
                      <td><ExecutionStatus status={item.status} /></td>
                      <td><strong className="mono">{item.window_from} ~ {item.window_to}</strong><span className="operations-row-sub">{item.job_kind === "daily" ? "일간" : "주간"} · <span className="mono">{item.run_key}</span></span></td>
                      <td>{triggerLabel(item.trigger)}<span className="operations-row-sub">{item.recovery_of_execution_id ? "명시 복구" : item.duplicate_of_execution_id ? "중복 요청" : "정기 실행"}</span></td>
                      <td><span className="mono">{item.execution_id}</span>{item.run_id ? <a className="operations-inline-link" href={`/runs?run=${encodeURIComponent(item.run_id)}`}>파생 회차 {item.run_id}</a> : <span className="operations-row-sub">파생 회차 없음</span>}</td>
                      <td><span className="operations-counts">후보 {formatNumber(item.candidate_count)} · 결과 {formatNumber(item.result_count)} · 실패 {formatNumber(item.failure_count)}</span>{item.partial_artifact ? <span className="operations-partial-indicator">부분 산출물</span> : null}</td>
                      <td><span className="operations-reason">{reasonLabel(item)}</span></td>
                      <td>{recoverable ? <button className="operations-recover-button" type="button" onClick={() => onRecover(item)}>복구</button> : null}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </section>
  );
}
