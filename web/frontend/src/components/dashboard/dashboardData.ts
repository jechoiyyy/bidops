import type { RunSummary, ValidationMetric } from "../../lib/types";
import { formatNumber, formatRunRangeCompact } from "../../lib/format";

export type DeadlineFilter = "week" | "urgent" | "checks";
export function deadlineFilter(value: string | null): DeadlineFilter {
  return value === "urgent" || value === "checks" ? value : "week";
}

// Dates belong to the immutable run snapshot, not the viewer's current clock.
export function daysFromReference(value: string | null, reference: string | null): number | null {
  if (!value || !reference) return null;
  const delta = Date.parse(value) - Date.parse(reference);
  return Number.isFinite(delta) ? Math.ceil(delta / 86_400_000) : null;
}

export function snapshotTime(value: string | null | undefined, timezone: string | null | undefined): string {
  if (!value || !Number.isFinite(Date.parse(value))) return "시각 미확인";
  if (!timezone) return "시간대 미확인";
  try {
    const parts = new Intl.DateTimeFormat("en-GB", {
      timeZone: timezone, month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hourCycle: "h23",
    }).formatToParts(new Date(value));
    const part = (key: string) => parts.find(item => item.type === key)?.value ?? "?";
    return `${part("month")}.${part("day")} ${part("hour")}:${part("minute")}`;
  } catch { return "시간대 미확인"; }
}

export function runOptionLabel(run: RunSummary): string {
  const range = formatRunRangeCompact(run.run_id, run.window_from, run.window_to);
  const kind = run.kind === "notices" ? "공고" : run.kind === "order_plans" ? "발주계획" : run.kind === "mixed" ? "혼합 자료" : "종류 미확인";
  return `${range} · ${kind}`;
}

export function runLink(path: string, runId: string | null, extra: Record<string, string> = {}): string {
  const params = new URLSearchParams(extra);
  if (runId) params.set("run", runId);
  return `${path}${params.size ? `?${params}` : ""}`;
}

export function metricStatus(metric: ValidationMetric): string {
  return metric.status === "pass" ? "통과" : metric.status === "fail" ? "미달" : metric.status === "measured" ? "측정" : "계산 불가";
}
export function metricValue(metric: ValidationMetric): string {
  if (metric.status === "not_measurable") return "계산 불가";
  if (metric.percentage !== null) return `${Number(metric.percentage.toFixed(1))}%`;
  return formatNumber(metric.value);
}
export function metricBasis(metric: ValidationMetric): string {
  if (metric.reason) return metric.reason;
  const { numerator, denominator } = metric.basis;
  return `근거 ${formatNumber(numerator)} / ${formatNumber(denominator)}건`;
}
