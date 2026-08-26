import type { ScreeningExecutionResponse } from "../../lib/types";

interface QualityGateRunsProps {
  passA: ScreeningExecutionResponse;
  passB: ScreeningExecutionResponse;
}

const terminalStatuses = new Set(["성공", "부분 성공", "실패", "중단됨"]);

function runStatus(run: ScreeningExecutionResponse): string {
  if (run.status === "실행 중" || run.status === "중지 요청") return "실행 중";
  return run.status;
}

function runStateDescription(run: ScreeningExecutionResponse): string {
  if (run.status === "대기") return run.queue_position ? `대기 순번 ${run.queue_position}` : "대기 중";
  if (run.status === "실행 중" || run.status === "중지 요청") {
    return [run.current_stage ?? "단계 확인 중", run.current_notice_id ? `공고 ${run.current_notice_id}` : null]
      .filter(Boolean)
      .join(" · ");
  }
  if (run.status === "부분 성공") return `완료 ${run.completed_count}건 · 실패 ${run.failure_count}건`;
  if (run.status === "성공") return `완료 ${run.completed_count}건`;
  return run.error_summary ?? "결과를 확인할 수 없습니다.";
}

function stateClass(run: ScreeningExecutionResponse): string {
  if (run.status === "성공") return "quality-state-passed";
  if (run.status === "부분 성공") return "quality-state-held";
  if (run.status === "실패" || run.status === "중단됨") return "quality-state-failed";
  return "quality-state-running";
}

function RunRow({ label, run }: { label: string; run: ScreeningExecutionResponse }) {
  const isTerminal = terminalStatuses.has(run.status);
  return (
    <article className={`quality-run-card ${stateClass(run)}`}>
      <div className="quality-run-card-heading">
        <div>
          <span className="quality-run-label">{label}</span>
          <strong className="mono">{run.execution_id}</strong>
        </div>
        <span className="quality-status" aria-label={`${label} 실행 상태 ${runStatus(run)}`}>{runStatus(run)}</span>
      </div>
      <p className="quality-run-description" aria-live="polite">{runStateDescription(run)}</p>
      <dl className="quality-run-facts">
        <div><dt>표본</dt><dd>{run.candidate_count}건</dd></div>
        <div><dt>완료</dt><dd>{run.completed_count}건</dd></div>
        <div><dt>실패</dt><dd>{run.failure_count}건</dd></div>
        <div><dt>상태 갱신</dt><dd>{run.heartbeat_at ? new Date(run.heartbeat_at).toLocaleString("ko-KR") : "시각 없음"}</dd></div>
      </dl>
      {isTerminal && run.published_run_id ? <p className="quality-run-link">파생 회차: <span className="mono">{run.published_run_id}</span></p> : null}
    </article>
  );
}

export function QualityGateRuns({ passA, passB }: QualityGateRunsProps) {
  return (
    <section className="quality-panel" aria-labelledby="quality-ab-heading">
      <div className="quality-panel-heading">
        <div>
          <span className="quality-eyebrow">실행 상태</span>
          <h2 id="quality-ab-heading">A/B 독립 실행</h2>
        </div>
        <span className="quality-readonly-note">두 실행은 같은 고정 입력을 사용합니다.</span>
      </div>
      <div className="quality-run-grid">
        <RunRow label="Pass A · 기준 실행" run={passA} />
        <RunRow label="Pass B · 재현 실행" run={passB} />
      </div>
    </section>
  );
}
