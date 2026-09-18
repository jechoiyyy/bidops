import type { OpportunityListItem, RunSummary, ValidationMetric } from "../../lib/types";
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

// 보류 재검토 패널(spec §8·§11.2). 목록 조건은 서버가 정하고 화면은 그대로 요청한다.
export const HOLD_REVIEW_LIMIT = 5;
// 사업 추적의 URL 동기화 이름(`section`·`reason`)을 그대로 쓴다.
export const HOLD_REVIEW_LIST_PATH = "/opportunities?section=조치 필요&reason=hold_overdue";

const KST_DATE = new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Seoul", year: "numeric", month: "2-digit", day: "2-digit" });
function kstDayIndex(time: number): number {
  const parts = KST_DATE.formatToParts(new Date(time));
  const part = (type: string) => Number(parts.find(item => item.type === type)?.value);
  return Date.UTC(part("year"), part("month") - 1, part("day")) / 86_400_000;
}

export type HoldReviewDue = { state: "overdue" | "due_soon" | "unknown"; label: string };
/**
 * 기한 지남 여부는 서버 사유 `hold_overdue`가 정한다. 화면은 한국 시간 날짜 차이만
 * `D+n`·`D-n`으로 옮긴다(표시 변환). 서버와 브라우저 시계가 자정 근처에서 어긋나도
 * 서버 판정을 뒤집지 않도록 날짜 차이는 0에서 멈춘다.
 */
export function holdReviewDue(item: Pick<OpportunityListItem, "hold_review_due_at" | "action_reasons">, now: number): HoldReviewDue {
  const due = Date.parse(item.hold_review_due_at ?? "");
  if (!Number.isFinite(due) || !Number.isFinite(now)) return { state: "unknown", label: "기한 미확인" };
  const days = kstDayIndex(due) - kstDayIndex(now);
  if (item.action_reasons.includes("hold_overdue")) return { state: "overdue", label: `기한 지남 D+${Math.max(0, -days)}` };
  return { state: "due_soon", label: `D-${Math.max(0, days)}` };
}
