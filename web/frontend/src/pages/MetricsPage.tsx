import { useQuery } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { EmptyState } from "../components/common/EmptyState";
import { Panel } from "../components/common/Panel";
import { api } from "../lib/api";
import { formatNumber, formatRunRange, runStatusLabel } from "../lib/format";
import type { RunSummary, ValidationMetric } from "../lib/types";
import "../styles/reference-relaxed.css";

function statusLabel(status: ValidationMetric["status"]): string {
  if (status === "pass") return "통과";
  if (status === "fail") return "미달";
  if (status === "measured") return "측정됨";
  return "계산 불가";
}

function thresholdLabel(threshold: unknown): string {
  if (threshold === null) return "사전 확정 임계값 없음";
  if (typeof threshold === "undefined") return "임계값 미확인";
  if (typeof threshold === "number" && Number.isFinite(threshold)) return `${Math.round(threshold * 100)}% 이상`;
  if (typeof threshold === "object" && threshold !== null && "min" in threshold && "max" in threshold) {
    const range = threshold as { min: unknown; max: unknown };
    if (typeof range.min === "number" && typeof range.max === "number" && Number.isFinite(range.min) && Number.isFinite(range.max)) {
      return `${Math.round(range.min * 100)}~${Math.round(range.max * 100)}%`;
    }
  }
  return "임계값 미확인";
}

function basisLabel(metric: ValidationMetric): string {
  const { numerator, denominator } = metric.basis;
  const numeratorLabel = typeof numerator === "number" && Number.isFinite(numerator) ? formatNumber(numerator) : "미확인";
  const denominatorLabel = typeof denominator === "number" && Number.isFinite(denominator) ? formatNumber(denominator) : "미확인";
  if (metric.status === "not_measurable") return `계산 대상 ${denominatorLabel}건 · 계산 불가`;
  return `분자 ${numeratorLabel} · 분모 ${denominatorLabel}`;
}

function valueLabel(metric: ValidationMetric): string {
  if (metric.percentage === null) return metric.status === "not_measurable" ? "계산 불가" : "값 미확인";
  return `${metric.percentage.toFixed(1)}%`;
}

function detailValueLabel(value: unknown): string {
  if (value === null || value === undefined) return "미확인";
  if (typeof value === "object") return JSON.stringify(value) ?? "값 미기록";
  if (typeof value === "string" && value.trim() === "") return "값 미기록";
  return String(value);
}

function basisDetailLabel(metric: ValidationMetric): string | null {
  const entries = Object.entries(metric.basis.detail ?? {});
  if (entries.length === 0) return null;
  return entries.map(([key, value]) => `${key} ${detailValueLabel(value)}`).join(" · ");
}

type MetricHistoryPoint = {
  value: number | null;
  state: "measured" | "not_measurable" | "unknown";
};

function metricHistory(history: ValidationMetric[][], key: string): MetricHistoryPoint[] {
  return history.map((metrics) => {
    const metric = metrics.find((item) => item.key === key);
    if (!metric) return { value: null, state: "unknown" };
    if (metric.status === "not_measurable") return { value: null, state: "not_measurable" };
    if (metric.percentage === null) return { value: null, state: "unknown" };
    return { value: metric.percentage, state: "measured" };
  });
}

function historyPointLabel(point: MetricHistoryPoint): string {
  if (point.state === "not_measurable") return "계산 불가";
  if (point.state === "unknown" || point.value === null) return "미확인";
  return `${point.value.toFixed(1)}%`;
}

function MetricTrend({ metric, history, runs }: { metric: ValidationMetric; history: ValidationMetric[][]; runs: RunSummary[] }) {
  if (history.length <= 1) return <p className="metrics-no-trend">비교할 회차가 없습니다</p>;
  const values = metricHistory(history, metric.key);
  const measured = values.map((item) => item.value).filter((value): value is number => value !== null);
  const maximum = Math.max(100, ...measured);
  return (
    <div className="metrics-trend" aria-label={`${metric.label} 회차별 추이`}>
      <div className="metrics-trend-heading"><span>회차</span><span>측정값</span></div>
      <ol className="metrics-trend-list">
        {values.map((item, index) => {
          const run = runs[index];
          const runId = run?.run_id ?? "회차 미확인";
          const range = run ? formatRunRange(run.run_id, run.window_from, run.window_to) : "회차 범위 미확인";
          const barHeight = item.value === null ? 0 : Math.min(100, Math.max(0, (item.value / maximum) * 100));
          return (
            <li className="metrics-trend-item" key={`${runId}:${index}`}>
              <div className="metrics-trend-run">
                <code>{runId}</code>
                <span>{range}</span>
              </div>
              <div className="metrics-trend-measure">
                <div className="metrics-trend-bar-track" aria-hidden="true">
                  {item.state === "measured" ? <span className="metrics-trend-bar" style={{ height: `${barHeight}%` }} /> : <span className="metrics-trend-unavailable">{item.state === "not_measurable" ? "계산 불가" : "미확인"}</span>}
                </div>
                <strong className="mono">{historyPointLabel(item)}</strong>
              </div>
            </li>
          );
        })}
      </ol>
    </div>
  );
}

function MetricCard({ metric, history, runs }: { metric: ValidationMetric; history: ValidationMetric[][]; runs: RunSummary[] }) {
  const detail = basisDetailLabel(metric);
  return (
    <article className={`metrics-card metrics-card-${metric.status}`}>
      <div className="metrics-card-heading">
        <div><span className="metrics-card-key mono">{metric.key}</span><h3>{metric.label}</h3></div>
        <span className={`metrics-status metrics-status-${metric.status}`}>{statusLabel(metric.status)}</span>
      </div>
      <div className="metrics-value-row">
        <div className="metrics-current-value"><span>현재 값</span><strong>{valueLabel(metric)}</strong></div>
        <div className="metrics-threshold"><span>임계값</span><strong>{thresholdLabel(metric.threshold)}</strong></div>
      </div>
      <div className="metrics-basis">
        <span>계산 근거</span>
        <strong className="mono">{basisLabel(metric)}</strong>
      </div>
      {detail ? <p className="metrics-basis-detail"><span>세부 근거</span>{detail}</p> : null}
      {metric.status === "not_measurable" ? <p className="metrics-reason"><span>계산 불가 사유</span>{metric.reason ?? "사유 미기록"}</p> : metric.reason ? <p className="metrics-reason"><span>설명</span>{metric.reason}</p> : null}
      <MetricTrend metric={metric} history={history} runs={runs} />
    </article>
  );
}

export function MetricsPage() {
  const [searchParams] = useSearchParams();
  const runsQuery = useQuery({ queryKey: ["runs"], queryFn: api.getRuns, staleTime: 30_000 });
  const runs = runsQuery.data?.items ?? [];
  const queryRunId = searchParams.get("run");
  const selectedRun = runs.find((run) => run.run_id === queryRunId) ?? runs.find((run) => run.counts.judgments > 0) ?? runs[0] ?? null;
  const selectedRunId = selectedRun?.run_id ?? null;
  const metricsQuery = useQuery({
    queryKey: ["validation-metrics", selectedRunId],
    queryFn: () => api.getValidationMetrics(selectedRunId as string),
    enabled: Boolean(selectedRunId),
    staleTime: 10_000,
  });
  const historyQuery = useQuery({
    queryKey: ["validation-metrics-history", runs.map((run) => run.run_id).join(",")],
    queryFn: async () => Promise.all(runs.map((run) => api.getValidationMetrics(run.run_id).then((response) => response.metrics))),
    enabled: runs.length > 0,
    staleTime: 10_000,
  });

  if (runsQuery.isLoading || metricsQuery.isLoading) return <div className="metrics-loading" role="status" aria-live="polite">검증 지표를 계산하는 중입니다.</div>;
  if (runsQuery.error || metricsQuery.error) {
    const error = runsQuery.error ?? metricsQuery.error;
    return <EmptyState title="검증 지표를 불러오지 못했습니다." description={error instanceof Error ? error.message : "지표 API 응답을 확인할 수 없습니다."} action={{ label: "다시 시도", onClick: () => { void runsQuery.refetch(); void metricsQuery.refetch(); } }} />;
  }
  if (!selectedRunId || !metricsQuery.data) return <EmptyState title="계산할 회차가 없습니다." description="판정이 적재된 회차가 있으면 검증 지표를 계산할 수 있습니다." />;

  const history = historyQuery.data ?? [metricsQuery.data.metrics];
  return (
    <div className="metrics-page">
      <header className="metrics-page-header">
        <div className="metrics-header-copy">
          <span className="metrics-eyebrow">기준 · 검증</span>
          <h2>검증 지표</h2>
          <p>통과 기준 다섯 항목을 산출물과 리뷰 기록에서 계산하고 회차별로 비교합니다.</p>
        </div>
        <div className="metrics-run-context"><span>현재 회차</span><strong className="metrics-run-id mono">{selectedRun.run_id}</strong><span>{formatRunRange(selectedRun.run_id, selectedRun.window_from, selectedRun.window_to)}</span></div>
      </header>
      <div className="metrics-notice"><strong>현재 회차 {formatRunRange(selectedRun.run_id, selectedRun.window_from, selectedRun.window_to)}</strong><span>각 카드의 계산 근거와 임계값을 함께 확인하십시오. 계산 불가는 0으로 대체하지 않습니다.</span></div>
      <Panel title="회차별 추이" className="metrics-history-panel">
        {historyQuery.error ? <p className="metrics-history-warning" role="alert">과거 회차 지표를 모두 불러오지 못했습니다. 현재 회차의 값과 계산 근거만 표시합니다.</p> : null}
        {history.length <= 1 ? <p className="metrics-no-trend metrics-no-trend-panel">비교할 회차가 없습니다</p> : <p className="metrics-history-caption">각 카드에서 회차별 값·상태를 확인할 수 있습니다. 계산 불가와 미확인은 별도 문구로 표시됩니다.</p>}
        {runs.length > 0 ? (
          <ol className="metrics-history-runs" aria-label="지표 조회 회차 목록">
            {runs.map((run, index) => (
              <li className={run.run_id === selectedRun.run_id ? "is-current" : ""} key={run.run_id}>
                <code>{run.run_id}</code>
                <span>{formatRunRange(run.run_id, run.window_from, run.window_to)}</span>
                <strong>{index < history.length ? runStatusLabel(run.status) : "지표 미확인"}</strong>
              </li>
            ))}
          </ol>
        ) : null}
      </Panel>
      <section className="metrics-grid" aria-label="검증 지표 목록">
        {metricsQuery.data.metrics.map((metric) => <MetricCard key={metric.key} metric={metric} history={history} runs={runs} />)}
      </section>
    </div>
  );
}
