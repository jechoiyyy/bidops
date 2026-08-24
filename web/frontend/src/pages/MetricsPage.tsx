import { useQuery } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { EmptyState } from "../components/common/EmptyState";
import { Panel } from "../components/common/Panel";
import { api } from "../lib/api";
import { formatNumber, formatRunRange } from "../lib/format";
import type { RunSummary, ValidationMetric } from "../lib/types";

function statusLabel(status: ValidationMetric["status"]): string {
  if (status === "pass") return "통과";
  if (status === "fail") return "미달";
  if (status === "measured") return "측정됨";
  return "계산 불가";
}

function thresholdLabel(threshold: unknown): string {
  if (typeof threshold === "number") return `${Math.round(threshold * 100)}% 이상`;
  if (typeof threshold === "object" && threshold !== null && "min" in threshold && "max" in threshold) {
    const range = threshold as { min: number; max: number };
    return `${Math.round(range.min * 100)}~${Math.round(range.max * 100)}%`;
  }
  return "사전 확정 임계값 없음";
}

function basisLabel(metric: ValidationMetric): string {
  const { numerator, denominator } = metric.basis;
  if (metric.status === "not_measurable") return `계산 대상 ${formatNumber(denominator)}건 · 계산 불가`;
  return `분자 ${formatNumber(numerator)} · 분모 ${formatNumber(denominator)}`;
}

function valueLabel(metric: ValidationMetric): string {
  if (metric.percentage === null) return "계산 불가";
  return `${metric.percentage.toFixed(1)}%`;
}

function metricHistory(history: ValidationMetric[][], key: string): Array<{ runId: string; value: number | null }> {
  return history.map((metrics, index) => ({
    runId: String(index),
    value: metrics.find((metric) => metric.key === key)?.percentage ?? null,
  }));
}

function MetricTrend({ metric, history, runs }: { metric: ValidationMetric; history: ValidationMetric[][]; runs: RunSummary[] }) {
  if (history.length <= 1) return <p className="metrics-no-trend">비교할 회차가 없습니다</p>;
  const values = metricHistory(history, metric.key);
  const measured = values.map((item) => item.value).filter((value): value is number => value !== null);
  const maximum = Math.max(100, ...measured);
  return (
    <div className="metrics-trend" aria-label={`${metric.label} 회차별 추이`}>
      <div className="metrics-trend-bars">
        {values.map((item, index) => (
          <div className="metrics-trend-column" key={`${item.runId}:${index}`}>
            <div className="metrics-trend-bar-track">
              {item.value === null ? <span className="metrics-trend-unavailable">계산 불가</span> : <span className="metrics-trend-bar" style={{ height: `${Math.max(6, (item.value / maximum) * 100)}%` }} />}
            </div>
            <span className="metrics-trend-label mono">{formatRunRange(runs[index].run_id, runs[index].window_from, runs[index].window_to)}</span>
            <strong className="mono">{item.value === null ? "계산 불가" : `${item.value.toFixed(1)}%`}</strong>
          </div>
        ))}
      </div>
    </div>
  );
}

function MetricCard({ metric, history, runs }: { metric: ValidationMetric; history: ValidationMetric[][]; runs: RunSummary[] }) {
  return (
    <article className={`metrics-card metrics-card-${metric.status}`}>
      <div className="metrics-card-heading">
        <div><span className="metrics-card-key mono">{metric.key}</span><h3>{metric.label}</h3></div>
        <span className={`metrics-status metrics-status-${metric.status}`}>{statusLabel(metric.status)}</span>
      </div>
      <div className="metrics-value-row">
        <strong>{valueLabel(metric)}</strong>
        <span>임계값 · {thresholdLabel(metric.threshold)}</span>
      </div>
      <div className="metrics-basis">
        <span>계산 근거</span>
        <strong className="mono">{basisLabel(metric)}</strong>
      </div>
      {metric.reason ? <p className="metrics-reason">{metric.reason}</p> : null}
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

  if (runsQuery.isLoading || metricsQuery.isLoading) return <div className="metrics-loading">검증 지표를 계산하는 중입니다.</div>;
  if (runsQuery.error || metricsQuery.error) {
    const error = runsQuery.error ?? metricsQuery.error;
    return <EmptyState title="검증 지표를 불러오지 못했습니다." description={error instanceof Error ? error.message : "지표 API 응답을 확인할 수 없습니다."} />;
  }
  if (!selectedRunId || !metricsQuery.data) return <EmptyState title="계산할 회차가 없습니다." description="판정이 적재된 회차가 있으면 검증 지표를 계산할 수 있습니다." />;

  const history = historyQuery.data ?? [metricsQuery.data.metrics];
  return (
    <div className="metrics-page">
      <header className="metrics-page-header">
        <div>
          <span className="metrics-eyebrow">기준 · 검증</span>
          <h2>검증 지표</h2>
          <p>통과 기준 다섯 항목을 산출물과 리뷰 기록에서 계산하고 회차별로 비교합니다.</p>
        </div>
        <div className="metrics-run-context"><span>선택 회차</span><strong className="mono">{formatRunRange(selectedRun.run_id, selectedRun.window_from, selectedRun.window_to)}</strong></div>
      </header>
      <div className="metrics-notice"><strong>현재 회차 {formatRunRange(selectedRun.run_id, selectedRun.window_from, selectedRun.window_to)}</strong><span>각 카드의 계산 근거와 임계값을 함께 확인하십시오. 계산 불가는 0으로 대체하지 않습니다.</span></div>
      <Panel title="회차별 추이" className="metrics-history-panel">
        {history.length <= 1 ? <p className="metrics-no-trend metrics-no-trend-panel">비교할 회차가 없습니다</p> : <p className="metrics-history-caption">각 막대는 해당 회차에서 계산된 비율입니다. 계산 불가 항목은 별도 문구로 표시됩니다.</p>}
      </Panel>
      <section className="metrics-grid" aria-label="통과 기준 지표">
        {metricsQuery.data.metrics.map((metric) => <MetricCard key={metric.key} metric={metric} history={history} runs={runs} />)}
      </section>
    </div>
  );
}
