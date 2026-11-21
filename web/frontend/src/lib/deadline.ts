export type DeadlineUrgency = "none" | "passed" | "critical" | "soon" | "later";

export interface DeadlineDisplay {
  label: string;
  urgency: DeadlineUrgency;
}

const DAY_MS = 86_400_000;
const KST_OFFSET_MS = 9 * 60 * 60 * 1000;
const clock = new Intl.DateTimeFormat("ko-KR", { timeZone: "Asia/Seoul", hour: "2-digit", minute: "2-digit", hourCycle: "h23" });

/** Count Korean calendar boundaries. A negative value always means the instant has passed. */
export function remainingDeadlineDays(date: Date, now: Date): number {
  const day = (time: Date) => Math.floor((time.getTime() + KST_OFFSET_MS) / DAY_MS);
  const difference = day(date) - day(now);
  return date < now ? Math.min(-1, difference) : difference;
}

export function deadlineLabel(days: number, date: Date): string {
  if (days < 0) return "마감 지남";
  if (days === 0) return `오늘 ${clock.format(date)} 마감`;
  return days === 1 ? "내일 마감" : `D-${days}`;
}

/** 목록은 먼 마감을 날짜로 줄이고 상세는 남은 일수를 모두 보여 준다. */
export function describeDeadline(value: string | null | undefined): DeadlineDisplay {
  const countdown = describeDeadlineCountdown(value);
  if (!countdown || !value) return { label: "마감 미확인", urgency: "none" };
  if (countdown.urgency === "later") return { ...countdown, label: formatShortDate(new Date(value)) };
  if (countdown.urgency === "passed") return { ...countdown, label: `마감 지남 · ${formatShortDate(new Date(value))}` };
  return countdown;
}

export function describeDeadlineCountdown(value: string | null | undefined): DeadlineDisplay | null {
  if (!value) return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return null;
  const days = remainingDeadlineDays(date, new Date());
  const urgency = days < 0 ? "passed" : days <= 3 ? "critical" : days <= 7 ? "soon" : "later";
  return { label: deadlineLabel(days, date), urgency };
}

/** `09.08` 꼴의 짧은 날짜. 목록의 마감 열이 D-day 아래에 같은 형식으로 쓴다. */
export function shortDateLabel(value: string | null | undefined): string | null {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : formatShortDate(date);
}

function formatShortDate(date: Date): string {
  return new Intl.DateTimeFormat("ko-KR", { timeZone: "Asia/Seoul", month: "2-digit", day: "2-digit" })
    .format(date)
    .replace(/\.\s?$/, "")
    .replace(/\.\s/, ".");
}

/** 억·만 단위로 줄여 목록 한 줄에 들어가게 만든다. */
export function formatCompactPrice(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "추정가격 미확인";
  const number = new Intl.NumberFormat("ko-KR", { maximumFractionDigits: 1 });
  if (value >= 100_000_000) return `${number.format(value / 100_000_000)}억원`;
  if (value >= 10_000) return `${number.format(value / 10_000)}만원`;
  return `${number.format(value)}원`;
}
