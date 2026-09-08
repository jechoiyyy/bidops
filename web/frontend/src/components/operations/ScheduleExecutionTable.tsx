import { Button } from "@astryxdesign/core/Button";
import { formatNumber } from "../../lib/format";
import type { ScheduleExecutionSummary, ScheduleStatus } from "../../lib/types";
import { Caption, DataTable, Section, StatusToken } from "../runs/RunStatusPrimitives";

interface ScheduleExecutionTableProps {
  items: ScheduleExecutionSummary[];
  onRecover: (item: ScheduleExecutionSummary) => void;
}

const recoverableStatuses: ScheduleStatus[] = ["실패", "부분 성공", "건너뜀"];
const scheduleStatuses: ScheduleStatus[] = ["예약", "실행 중", "성공", "부분 성공", "실패", "건너뜀"];

export function executionAnchor(executionId: string): string {
  return `schedule-execution-${encodeURIComponent(executionId)}`;
}

function triggerLabel(trigger: ScheduleExecutionSummary["trigger"]): string {
  return trigger === "manual" ? "수동" : "예약";
}

function reasonLabel(item: ScheduleExecutionSummary): string {
  if (item.skip_reason) return `건너뜀 사유 · ${item.skip_reason}`;
  if (item.failure_reason) return `실패 사유 · ${item.failure_reason}`;
  if (item.status === "부분 성공" && item.partial_artifact) return "부분 산출물 기록됨";
  return "사유 없음";
}

/**
 * 정기 실행 이력.
 *
 * 건수의 `null`은 0이 아니라 값 없음이다. 예약·실제 실행·결과 게시를 구분하고,
 * 거절된 예약을 실행 성공으로 표시하지 않는다.
 */
export function ScheduleExecutionTable({ items, onRecover }: ScheduleExecutionTableProps) {
  const counts = items.reduce<Partial<Record<ScheduleStatus, number>>>((result, item) => {
    result[item.status] = (result[item.status] ?? 0) + 1;
    return result;
  }, {});

  return (
    <Section title="정기 실행 이력" action={<Caption as="span">{items.length}건</Caption>}>
      <div className="rs-link-row" aria-label="정기 실행 상태 범례">
        {scheduleStatuses.map((status) => (
          <span className="rs-row" key={status}>
            <StatusToken label={status} />
            <Caption as="span">{counts[status] ?? 0}건</Caption>
          </span>
        ))}
      </div>
      {items.length === 0 ? (
        <Caption>아직 예약·catch-up·실행 이력이 없습니다.</Caption>
      ) : (
        <DataTable
          caption="정기 실행 상태와 기간, 실행 결과, 실패·건너뜀 사유"
          headings={["상태", "기간 · 종류", "트리거", "실행·파생", "건수", "사유", "복구"]}
          rows={items.map((item) => ({
            id: item.execution_id,
            cells: [
              <StatusToken key="status" label={item.status} />,
              <span key="window" id={executionAnchor(item.execution_id)}>
                <span className="rs-mono">{item.window_from} ~ {item.window_to}</span>
                <span className="rs-row-sub">{item.job_kind === "daily" ? "일간" : "주간"} · <span className="rs-mono">{item.run_key}</span></span>
              </span>,
              <span key="trigger">
                {triggerLabel(item.trigger)}
                {item.recovery_of_execution_id ? (
                  <span className="rs-row-sub">
                    <a href={`#${executionAnchor(item.recovery_of_execution_id)}`}>복구 대상 · {item.recovery_of_execution_id}</a>
                  </span>
                ) : null}
                {item.duplicate_of_execution_id ? (
                  <span className="rs-row-sub">
                    <a href={`#${executionAnchor(item.duplicate_of_execution_id)}`}>중복 대상 · {item.duplicate_of_execution_id}</a>
                  </span>
                ) : null}
                {!item.recovery_of_execution_id && !item.duplicate_of_execution_id ? <span className="rs-row-sub">정기 실행</span> : null}
              </span>,
              <span key="ids">
                <span className="rs-mono">{item.execution_id}</span>
                <span className="rs-row-sub">{item.run_id ? `파생 회차 ${item.run_id}` : "파생 회차 없음"}</span>
              </span>,
              <span key="counts">
                후보 {formatNumber(item.candidate_count)} · 결과 {formatNumber(item.result_count)} · 실패 {formatNumber(item.failure_count)}
                {item.partial_artifact ? <span className="rs-row-sub">부분 산출물</span> : null}
              </span>,
              <span key="reason">{reasonLabel(item)}</span>,
              recoverableStatuses.includes(item.status)
                ? <Button key="recover" label="복구" size="sm" onClick={() => onRecover(item)} />
                : <span key="none" className="rs-row-sub">복구 대상 아님</span>,
            ],
          }))}
        />
      )}
      <Caption>
        건수의 &quot;값 없음&quot;은 0건이 아니라 서버가 기록하지 않은 상태입니다. 거절되거나 건너뛴 예약을
        실행 성공으로 표시하지 않습니다.
      </Caption>
    </Section>
  );
}
