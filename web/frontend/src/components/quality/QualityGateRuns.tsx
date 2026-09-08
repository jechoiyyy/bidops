import { Text } from "@astryxdesign/core/Text";
import { DataTable, Section, Small, StatusToken } from "../criteria/CriteriaPrimitives";
import type { ScreeningExecutionResponse } from "../../lib/types";

interface QualityGateRunsProps {
  passA: ScreeningExecutionResponse;
  passB: ScreeningExecutionResponse;
}

const TERMINAL_STATUSES = new Set(["성공", "부분 성공", "실패", "중단됨"]);

/**
 * A/B 두 실행의 상태.
 *
 * 성공·부분 성공·실패·중단·대기·중지 요청을 서로 구분하고, 실패 요약과 파생 회차를
 * 숨기지 않는다(`web/frontend/AGENTS.md` "상태 표현"). 진행 문구는 서버가 준 단계·
 * 공고·건수만 쓰고 분모 없는 백분율이나 예상 시간을 만들지 않는다.
 */
function stateDescription(run: ScreeningExecutionResponse): string {
  if (run.status === "대기") return run.queue_position ? `대기 순번 ${run.queue_position}` : "대기 중";
  if (run.status === "중지 요청") {
    return ["중지 요청 처리 중", run.current_stage ?? "단계 확인 중", run.current_notice_id ? `공고 ${run.current_notice_id}` : null]
      .filter(Boolean).join(" · ");
  }
  if (run.status === "실행 중") {
    return [run.current_stage ?? "단계 확인 중", run.current_notice_id ? `공고 ${run.current_notice_id}` : null]
      .filter(Boolean).join(" · ");
  }
  if (run.status === "부분 성공") return `완료 ${run.completed_count}건 · 실패 ${run.failure_count}건`;
  if (run.status === "성공") return `완료 ${run.completed_count}건`;
  return run.error_summary ?? "결과를 확인할 수 없습니다.";
}

function runRow(label: string, run: ScreeningExecutionResponse) {
  return [
    <span className="crit-cell-stack" key="run">
      <Text weight="semibold">{label}</Text>
      <Small><code>{run.execution_id}</code></Small>
    </span>,
    <StatusToken key="status" label={run.status} />,
    <span className="crit-cell-stack" key="progress">
      <Text>{stateDescription(run)}</Text>
      <Small>{`표본 ${run.candidate_count}건 · 완료 ${run.completed_count}건 · 실패 ${run.failure_count}건`}</Small>
    </span>,
    <span className="crit-cell-stack" key="meta">
      <Text>{run.heartbeat_at ? new Date(run.heartbeat_at).toLocaleString("ko-KR") : "상태 갱신 시각 없음"}</Text>
      {TERMINAL_STATUSES.has(run.status) && run.published_run_id ? <Small>{`파생 회차 ${run.published_run_id}`}</Small> : null}
    </span>,
  ];
}

export function QualityGateRuns({ passA, passB }: QualityGateRunsProps) {
  return (
    <Section title="A/B 독립 실행">
      <Small>두 실행은 같은 고정 입력을 사용합니다. 실행 종결이 품질 통과를 뜻하지 않습니다.</Small>
      <DataTable
        caption="A/B 실행 상태"
        headings={["실행", "상태", "진행", "상태 갱신"]}
        rows={[runRow("Pass A · 기준 실행", passA), runRow("Pass B · 재현 실행", passB)]}
      />
    </Section>
  );
}
