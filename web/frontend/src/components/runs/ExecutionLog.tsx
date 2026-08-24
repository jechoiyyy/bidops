import type { PipelineLogResponse } from "../../lib/types";
import { formatDateTime } from "../../lib/format";

interface ExecutionLogProps {
  data: PipelineLogResponse | undefined;
  loading: boolean;
  error: unknown;
}

export function ExecutionLog({ data, loading, error }: ExecutionLogProps) {
  const running = data?.executions.some((execution) => execution.status === "pending" || execution.status === "running");
  return (
    <section className="panel runs-panel">
      <div className="panel-header"><h3>실행 로그</h3><span className="panel-meta">{running ? "실행 중 · 자동 갱신" : data?.executions.length ? `${data.executions.length}회 실행 기록` : "실행 기록 없음"}</span></div>
      <div className="panel-body">
        {loading && !data ? <p className="runs-empty-value">로그를 불러오는 중입니다.</p> : null}
        {error ? <p className="runs-error" role="alert">실행 로그를 불러오지 못했습니다.</p> : null}
        {!loading && !error && data && data.items.length === 0 ? <p className="runs-empty-value">아직 기록된 로그가 없습니다.</p> : null}
        {data?.executions.map((execution) => (
          <div className="runs-log-execution" key={execution.execution_id}>
            <div className="runs-log-execution-heading">
              <strong>{execution.stage === "collect" ? "수집" : execution.stage === "sample" ? "표본 선정" : "보고 생성"}</strong>
              <span className={`runs-status runs-status-${execution.status}`}>{execution.status === "running" ? "진행 중" : execution.status === "failed" ? "실패" : execution.status === "pending" ? "대기 중" : "성공"}</span>
              <span className="mono">{formatDateTime(execution.started_at)}</span>
            </div>
            {execution.error ? <p className="runs-log-error">{execution.error}</p> : null}
          </div>
        ))}
        {data?.items.length ? (
          <div className="runs-log-lines" aria-live={running ? "polite" : "off"}>
            {data.items.map((line, index) => (
              <div className={`runs-log-line runs-log-line-${line.level}`} key={`${line.timestamp}-${index}`}>
                <time className="mono">{formatDateTime(line.timestamp)}</time><span>{line.message}</span>
              </div>
            ))}
          </div>
        ) : null}
      </div>
    </section>
  );
}
