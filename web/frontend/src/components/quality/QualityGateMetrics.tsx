import type { JsonValue, QualityGateResultStatus, RuntimeJsonObject } from "../../lib/types";

interface MetricEntry {
  key: string;
  metric: Record<string, unknown>;
}

interface QualityGateMetricsProps {
  metrics: RuntimeJsonObject;
  resultStatus: QualityGateResultStatus;
}

function record(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null;
}

function isMetric(value: unknown): value is Record<string, unknown> {
  const item = record(value);
  return item !== null && ["numerator", "denominator", "percent", "status"].some((key) => key in item);
}

function flattenMetrics(source: RuntimeJsonObject): MetricEntry[] {
  const entries: MetricEntry[] = [];
  function visit(value: unknown, path: string) {
    if (isMetric(value)) {
      entries.push({ key: path, metric: value });
      return;
    }
    const item = record(value);
    if (!item) return;
    Object.entries(item).forEach(([key, nested]) => visit(nested, path ? `${path}.${key}` : key));
  }
  Object.entries(source).forEach(([key, value]) => {
    if (key !== "excluded_notices") visit(value, key);
  });
  return entries;
}

function numberValue(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function textValue(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value : null;
}

function jsonLabel(value: JsonValue): string {
  if (value === null || value === undefined) return "정보 없음";
  if (typeof value === "string") return value;
  try {
    return JSON.stringify(value);
  } catch {
    return "정보를 표시할 수 없음";
  }
}

function metricStatus(value: unknown): string {
  const status = textValue(value);
  if (status === "통과" || status === "pass") return "통과";
  if (status === "미달" || status === "fail") return "미달";
  if (status === "보류" || status === "held") return "보류";
  if (status === "미측정" || status === "unmeasured") return "미측정";
  if (status === "해당 없음") return "해당 없음";
  return status ?? "계산 불가";
}

function percentLabel(value: unknown): string {
  const percent = numberValue(value);
  return percent === null ? "계산 불가" : `${percent.toFixed(2)}%`;
}

function thresholdLabel(value: unknown): string {
  if (value === undefined || value === null) return "임계값 정보 없음";
  return `임계값 · ${jsonLabel(value)}`;
}

function metricClass(status: string): string {
  if (status === "통과") return "quality-metric-passed";
  if (status === "미달") return "quality-metric-failed";
  if (status === "보류") return "quality-metric-held";
  if (status === "미측정") return "quality-metric-unmeasured";
  return "quality-metric-unavailable";
}

export function QualityGateMetrics({ metrics, resultStatus }: QualityGateMetricsProps) {
  const entries = flattenMetrics(metrics);
  const excluded = Array.isArray(metrics.excluded_notices)
    ? metrics.excluded_notices.map((item) => record(item)).filter((item): item is Record<string, unknown> => item !== null)
    : [];
  const sampleCount = numberValue(metrics.sample_count);
  const pairedCount = numberValue(metrics.paired_valid_count);

  return (
    <section className="quality-panel" aria-labelledby="quality-metrics-heading">
      <div className="quality-panel-heading">
        <div>
          <span className="quality-eyebrow">결정적 계산</span>
          <h2 id="quality-metrics-heading">지표와 제외 근거</h2>
        </div>
        <span className="quality-status" aria-live="polite">최종 상태 · {resultStatus}</span>
      </div>
      <div className="quality-metric-summary" aria-label="표본 요약">
        <div><span>고정 표본</span><strong>{sampleCount === null ? "계산 불가" : `${sampleCount}건`}</strong></div>
        <div><span>A/B 유효 쌍</span><strong>{pairedCount === null ? "계산 불가" : `${pairedCount}건`}</strong></div>
        <div><span>지표 수</span><strong>{entries.length}개</strong></div>
      </div>
      {entries.length > 0 ? (
        <div className="quality-table-wrap">
          <table className="quality-metric-table">
            <caption className="quality-sr-only">품질 게이트 지표별 계산 결과와 임계값</caption>
            <thead><tr><th scope="col">지표</th><th scope="col">결과</th><th scope="col">계산 근거</th><th scope="col">상태</th><th scope="col">임계값·사유</th></tr></thead>
            <tbody>
              {entries.map(({ key, metric }) => {
                const status = metricStatus(metric.status);
                const numerator = numberValue(metric.numerator);
                const denominator = numberValue(metric.denominator);
                return (
                  <tr className={metricClass(status)} key={key}>
                    <th scope="row"><code>{key}</code></th>
                    <td><strong>{percentLabel(metric.percent)}</strong></td>
                    <td>{numerator === null || denominator === null ? "계산 불가" : <span className="mono">{numerator} / {denominator}</span>}</td>
                    <td><span className="quality-status">{status}</span></td>
                    <td>
                      <span>{thresholdLabel(metric.threshold)}</span>
                      {textValue(metric.reason) ? <small>{textValue(metric.reason)}</small> : null}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="quality-empty-inline" role="status">아직 계산된 지표가 없습니다. 실행 상태와 입력 표본을 확인하십시오.</p>
      )}
      <div className="quality-excluded" aria-labelledby="quality-excluded-heading">
        <h3 id="quality-excluded-heading">제외된 공고와 사유</h3>
        {excluded.length > 0 ? (
          <ul>
            {excluded.map((item, index) => <li key={`${textValue(item.notice_id) ?? "notice"}-${index}`}><span className="mono">{textValue(item.notice_id) ?? "공고 ID 없음"}</span><span>{textValue(item.pass) ?? "검토"} · {textValue(item.reason) ?? "제외 사유 없음"}</span></li>)}
          </ul>
        ) : <p>제외된 공고가 없습니다.</p>}
      </div>
    </section>
  );
}
