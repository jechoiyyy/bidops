export type DeadlineUrgency = "none" | "passed" | "critical" | "soon" | "later";

export interface DeadlineDisplay {
  label: string;
  urgency: DeadlineUrgency;
}

const DAY_MS = 86_400_000;

/**
 * 마감까지 남은 기간을 등급으로 나눈다.
 * 목록의 우측 칩과 상세 헤더가 같은 기준을 쓰도록 한곳에서 계산한다.
 * 3일 이내는 채운 칩, 7일 이내는 테두리 칩, 그보다 멀면 날짜만 보여 준다.
 */
export function describeDeadline(value: string | null | undefined): DeadlineDisplay {
  if (!value) return { label: "마감 미확인", urgency: "none" };
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return { label: "마감 미확인", urgency: "none" };

  const remaining = date.getTime() - Date.now();
  if (remaining < 0) {
    return { label: `마감 지남 · ${formatShortDate(date)}`, urgency: "passed" };
  }
  const days = Math.ceil(remaining / DAY_MS);
  if (days <= 3) return { label: `D-${days}`, urgency: "critical" };
  if (days <= 7) return { label: `D-${days}`, urgency: "soon" };
  return { label: formatShortDate(date), urgency: "later" };
}

/** `09.08` 꼴의 짧은 날짜. 목록의 마감 열이 D-day 아래에 같은 형식으로 쓴다. */
export function shortDateLabel(value: string | null | undefined): string | null {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : formatShortDate(date);
}

function formatShortDate(date: Date): string {
  return new Intl.DateTimeFormat("ko-KR", { month: "2-digit", day: "2-digit" })
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
