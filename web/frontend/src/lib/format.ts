export function present(value: unknown, fallback = "값 없음"): string {
  if (value === null || value === undefined) return fallback;
  if (typeof value === "string" && value.trim() === "") return fallback;
  return String(value);
}

export function formatRunRange(
  runId: string,
  windowFrom: string | null,
  windowTo: string | null,
): string {
  if (!windowFrom || !windowTo) return present(runId, "회차 미확인");
  const from = windowFrom.slice(0, 10);
  const to = windowTo.slice(0, 10);
  return `${from} ~ ${to}`;
}

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return "시각 미확인";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "시각 미확인";
  return new Intl.DateTimeFormat("ko-KR", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

export function formatNumber(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "값 없음";
  return new Intl.NumberFormat("ko-KR").format(value);
}

export function formatPrice(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "추정가격 미확인";
  return `${formatNumber(value)}원`;
}

export function formatDate(value: string | null | undefined): string {
  if (!value) return "일자 미확인";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "일자 미확인";
  return new Intl.DateTimeFormat("ko-KR", { dateStyle: "medium" }).format(date);
}

export function formatDeadline(value: string | null | undefined): string {
  if (!value) return "마감 미확인";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "마감 미확인";
  const remaining = date.getTime() - Date.now();
  if (remaining < 0) return `마감 지남 · ${formatDate(value)}`;
  const days = Math.ceil(remaining / 86_400_000);
  if (days <= 7) return `D-${days}`;
  return formatDate(value);
}

export function formatTime(value: string | null | undefined): string {
  if (!value) return "시각 미확인";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "시각 미확인";
  return new Intl.DateTimeFormat("ko-KR", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

// 상단 바의 회차 선택기는 폭이 좁으므로 연도를 한 번만 적는 축약형을 쓴다.
export function formatRunRangeCompact(
  runId: string,
  windowFrom: string | null,
  windowTo: string | null,
): string {
  if (!windowFrom || !windowTo) return present(runId, "회차 미확인");
  const from = windowFrom.slice(0, 10).replace(/-/g, ".");
  const to = windowTo.slice(5, 10).replace(/-/g, ".");
  return `${from}–${to}`;
}

export function runStatusLabel(status: string): string {
  if (status === "superseded") return "대체됨";
  if (status === "active") return "완료";
  return present(status, "상태 미확인");
}
