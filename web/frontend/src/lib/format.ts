export function present(value: unknown, fallback = "값 없음"): string {
  if (value === null || value === undefined) return fallback;
  if (typeof value === "string" && value.trim() === "") return fallback;
  return String(value);
}

/** 목록·필터·건수 표기의 천 단위 구분. 한국어 로캘 하나만 쓴다(U3, `WorkspaceFilters.formatCount`에서 옮김). */
export function formatCount(count: number): string {
  return count.toLocaleString("ko-KR");
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

/**
 * 날짜·시각 하나를 로캘 기본 표기로 적는다(초 포함). null이면 `nullLabel`을 쓴다
 * (기본 `미확인`). 화면마다 null 문구의 뜻이 달라(`미확인`·`값 없음`·`기록 없음`)
 * 한 함수로 강제하지 않는다 — 대신 그 문구를 두 번째 인자로 받는다(U3, 중복 통합).
 *
 * `formatDateTime`과 다르다: 이쪽은 `Date.prototype.toLocaleString`을 그대로 쓰므로
 * 초 단위까지 나온다. 초를 지운 짧은 표기가 필요하면 `formatDateTime`을 쓴다.
 */
export function formatMoment(value: string | null | undefined, nullLabel = "미확인"): string {
  if (!value) return nullLabel;
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString("ko-KR");
}

function currentKstYear(): number {
  return Number(new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Seoul", year: "numeric" }).format(new Date()));
}

/** {@link formatRunRangeShort}가 받는 최소 모양. `RunSummary`를 그대로 넘길 수 있다. */
export interface RunRangeShortInput {
  run_id: string;
  window_from: string | null;
  window_to: string | null;
}

/**
 * 회차 선택기 옵션의 짧은 수집 기간 표기(U3, 명세 §2.1·M1).
 *
 * `MM-DD~MM-DD`, 같은 날이면 `MM-DD` 하나만. 수집 기간의 해가 올해와 다르면
 * `YYYY-MM-DD`로 연도를 남긴다 — 전체 표기가 필요한 자리는 기존 `formatRunRange`를
 * 그대로 쓴다. `window_from`·`window_to`는 이미 KST 관측일 문자열이라 별도 시간대
 * 변환은 하지 않는다(`formatRunRange`와 같은 방식).
 */
export function formatRunRangeShort(run: RunRangeShortInput): string {
  const { run_id, window_from, window_to } = run;
  if (!window_from || !window_to) return present(run_id, "회차 미확인");
  const currentYear = String(currentKstYear());
  const sameYearAsNow = window_from.slice(0, 4) === currentYear && window_to.slice(0, 4) === currentYear;
  const short = (value: string) => (sameYearAsNow ? value.slice(5, 10) : value);
  return window_from === window_to ? short(window_from) : `${short(window_from)}~${short(window_to)}`;
}

const KST_MOMENT_PARTS = new Intl.DateTimeFormat("en-CA", {
  timeZone: "Asia/Seoul",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});

/**
 * 회차 선택기 옵션 설명의 짧은 생성 시각 표기(U3, 명세 §2.1·M1): `MM-DD HH:mm`(KST).
 * 해가 올해와 다르면 `YYYY-MM-DD HH:mm`으로 연도를 남긴다({@link formatRunRangeShort}와
 * 같은 규칙).
 */
export function formatMomentShort(value: string | null | undefined): string {
  if (!value) return "시각 미확인";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "시각 미확인";
  const parts = Object.fromEntries(KST_MOMENT_PARTS.formatToParts(date).map((part) => [part.type, part.value])) as
    Record<"year" | "month" | "day" | "hour" | "minute", string>;
  const sameYear = parts.year === String(currentKstYear());
  const datePart = sameYear ? `${parts.month}-${parts.day}` : `${parts.year}-${parts.month}-${parts.day}`;
  return `${datePart} ${parts.hour}:${parts.minute}`;
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

/** 추정가격은 나라장터가 준 원문 수집값이다. 서버 null은 사람 확인 대기가 아니라
 * 원천이 값을 주지 않았다는 뜻이라 `미제공`으로 적는다(U3, spec §1.1). */
export function formatPrice(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "추정가격 미제공";
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
