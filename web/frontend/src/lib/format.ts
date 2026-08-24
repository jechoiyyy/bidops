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
