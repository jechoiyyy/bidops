import { Panel } from "../common/Panel";
import type { ValidationMetric } from "../../lib/types";
import { formatNumber } from "../../lib/format";

interface ValidationGaugesProps {
  metrics: ValidationMetric[];
}

const metricOrder = [
  "discriminative_power",
  "perspective_split",
  "evidence_validity",
  "reproducibility",
  "information_sufficiency",
];

function orderedMetrics(metrics: ValidationMetric[]): ValidationMetric[] {
  const known = metricOrder.flatMap((key) => metrics.filter((metric) => metric.key === key));
  const rest = metrics.filter((metric) => !metricOrder.includes(metric.key));
  return [...known, ...rest];
}

function formatPercent(value: number): string {
  return `${Number.isInteger(value) ? value.toFixed(0) : value.toFixed(1)}%`;
}

function formatThreshold(threshold: unknown): string {
  if (typeof threshold === "number") return `${formatPercent(threshold * 100)} 이상`;
  if (typeof threshold === "object" && threshold !== null && "min" in threshold && "max" in threshold) {
    const range = threshold as { min: unknown; max: unknown };
    if (typeof range.min === "number" && typeof range.max === "number") {
      return `${formatPercent(range.min * 100)}~${formatPercent(range.max * 100)}`;
    }
  }
  return "사전 임계값 없음";
}

function currentValue(metric: ValidationMetric): string {
  if (metric.status === "not_measurable" || metric.percentage === null) return "계산 불가";
  return formatPercent(metric.percentage);
}

function basisLabel(metric: ValidationMetric): string {
  const { numerator, denominator } = metric.basis;
  return `${formatNumber(numerator)} / ${formatNumber(denominator)}건`;
}

function statusLabel(metric: ValidationMetric): string {
  if (metric.status === "not_measurable") return "계산 불가";
  if (metric.status === "fail") return "미달";
  if (metric.status === "pass") return "통과";
  return "측정";
}

function gaugeWidth(metric: ValidationMetric): number {
  if (metric.percentage === null || metric.status === "not_measurable") return 0;
  if (typeof metric.threshold === "object" && metric.threshold !== null && "max" in metric.threshold) {
    const max = (metric.threshold as { max: unknown }).max;
    if (typeof max === "number" && max > 0) return Math.min((metric.value ?? 0) / max, 1) * 100;
  }
  return Math.min(Math.max(metric.percentage, 0), 100);
}

export function ValidationGauges({ metrics }: ValidationGaugesProps) {
  const rows = orderedMetrics(metrics);
  const failed = rows.filter((metric) => metric.status === "fail").length;

  return (
    <Panel
      className="dashboard-validation-panel"
      title="검증 통과 기준"
      action={<span className="panel-note">5개 항목 중 {formatNumber(failed)}개 미달</span>}
    >
      <div className="dashboard-validation-list">
        {rows.length === 0 ? (
          <div className="dashboard-inline-empty">검증 지표 없음</div>
        ) : (
          rows.map((metric) => {
            const unavailable = metric.status === "not_measurable" || metric.percentage === null;
            return (
              <div className={`dashboard-validation-row ${unavailable ? "is-unavailable" : ""}`} key={metric.key}>
                <div className="dashboard-validation-heading">
                  <div className="dashboard-validation-label">
                    <strong>{metric.label || "지표 미확인"}</strong>
                    <span className="dashboard-validation-status">{statusLabel(metric)}</span>
                  </div>
                  <div className="dashboard-validation-values mono tabular-nums">
                    <span className={metric.status === "fail" ? "is-fail" : ""}>{currentValue(metric)}</span>
                    <span className="dashboard-validation-threshold">/ {formatThreshold(metric.threshold)}</span>
                  </div>
                </div>
                <div className={`dashboard-validation-gauge ${unavailable ? "is-unavailable" : ""}`} aria-label={unavailable ? "계산 불가" : `${currentValue(metric)} 게이지`}>
                  {!unavailable ? <span style={{ width: `${gaugeWidth(metric)}%` }} /> : null}
                </div>
                {unavailable && metric.reason ? <p className="dashboard-validation-reason">{metric.reason}</p> : null}
                {!unavailable ? <div className="dashboard-validation-basis mono tabular-nums">근거 {basisLabel(metric)}</div> : null}
              </div>
            );
          })
        )}
      </div>
    </Panel>
  );
}
