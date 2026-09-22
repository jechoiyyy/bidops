import type { OpportunityLinkView, OpportunityListItem } from "../../lib/types";
import { shortDateLabel } from "../../lib/deadline";
import { isConfirmedLink, stageOfLink } from "../opportunities/trackingFlow";

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

/** 누적 업무 패널이 보여 주는 목록 길이. 건수는 `/api/workload`가 따로 낸다(ADR-0067 결정 7). */
export const WORK_PANEL_LIMIT = 5;
/** `마감 임박 추적 건`의 창(일). 서버 `DEADLINE_IMMINENT_WINDOW_DAYS`와 같은 값이다. */
export const DEADLINE_IMMINENT_DAYS = 7;
/** 이 안쪽의 D-day를 강조한다(M6 승인 2026-09-22). */
export const DEADLINE_URGENT_DAYS = 3;

/**
 * `first_observed_from`에 보낼 **요청 시각 KST 일자 −1일**(`YYYY-MM-DD`).
 *
 * 창은 하한만 둔다 — 아침 cron이 그날 07:00에 넣은 도착분도 "새로"에 들어야 한다
 * (spec §7.3, 리더 채택 2026-09-22).
 */
export function previousKstDate(now: number): string {
  return new Date((kstDayIndex(now) - 1) * 86_400_000).toISOString().slice(0, 10);
}

/** 대표 마감의 종류. 서버는 대표 마감을 고르지 않으므로 화면이 링크에서 읽는다. */
export type DeadlineKind = "입찰 마감" | "의견등록 마감" | "마감 종류 미확인";
export interface ImminentDeadline {
  kind: DeadlineKind;
  deadlineAt: string;
  days: number;
  urgent: boolean;
}

/**
 * `마감 임박 추적 건` 행이 적을 마감 하나(ADR-0067 결정 4).
 *
 * 서버는 창을 **링크 단위**로 판정하고 사업을 돌려주므로 응답에 "이 사업의 마감"이
 * 없다. 화면은 서버와 같은 술어(권위 있는 연결 = `isConfirmedLink`)를 적용한 링크 중
 * **아직 지나지 않은 마감이 가장 이른 것**을 골라 종류를 적는다. 그런 링크가 없으면
 * 마감을 지어내지 않고 `null`이다.
 */
export function imminentDeadline(item: { links: readonly OpportunityLinkView[] }, now: number): ImminentDeadline | null {
  let best: { link: OpportunityLinkView; at: number } | null = null;
  for (const link of item.links) {
    if (!isConfirmedLink(link) || !link.deadline_at) continue;
    const at = Date.parse(link.deadline_at);
    if (!Number.isFinite(at) || at < now) continue;
    if (!best || at < best.at) best = { link, at };
  }
  if (!best || !best.link.deadline_at) return null;
  const stage = stageOfLink(best.link);
  const kind: DeadlineKind = stage === "입찰공고" ? "입찰 마감" : stage === "사전규격" ? "의견등록 마감" : "마감 종류 미확인";
  const days = Math.ceil((best.at - now) / 86_400_000);
  return { kind, deadlineAt: best.link.deadline_at, days, urgent: days <= DEADLINE_URGENT_DAYS };
}

/**
 * `최종 결정 대기` 행 오른쪽의 입찰 마감 한 마디. Go/No-Go 대기열 열(F3)과 같은
 * 계산이며, 좁은 패널이라 날짜는 지난 마감에만 붙인다. `null`은 서버가 값을 안 준
 * 것이므로(spec §1.1) `마감 미확인`이 아니라 `마감 미제공`이다.
 */
export function queueDeadlineLabel(value: string | null, now: number): { text: string; urgent: boolean } {
  const at = value === null ? Number.NaN : Date.parse(value);
  if (!Number.isFinite(at)) return { text: "마감 미제공", urgent: false };
  if (at < now) return { text: `마감 지남 · ${shortDateLabel(value) ?? ""}`.trim(), urgent: false };
  const days = Math.ceil((at - now) / 86_400_000);
  return { text: `D-${days}`, urgent: days <= DEADLINE_URGENT_DAYS };
}

const KST_DAY = new Intl.DateTimeFormat("en-GB", { timeZone: "Asia/Seoul", month: "2-digit", day: "2-digit" });
/** 한국 시간 `MM.DD`. 값이 없거나 파싱할 수 없으면 `null`이며 날짜를 지어내지 않는다. */
function kstDayLabel(value: string | null | undefined): string | null {
  if (!value || !Number.isFinite(Date.parse(value))) return null;
  const parts = KST_DAY.formatToParts(new Date(value));
  const part = (key: string) => parts.find(item => item.type === key)?.value;
  const month = part("month"), day = part("day");
  return month && day ? `${month}.${day}` : null;
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

/**
 * `보류 재검토` 행 오른쪽 한 마디(S1 — 표를 다른 패널과 같은 행으로 옮기며 생겼다).
 *
 * 다른 업무 패널의 `end`와 같이 짧은 한 칸이다. 기한 지남만 강조하며, 기한을 받지
 * 못한 행은 `기한 미확인`으로 두고 지남이나 0으로 바꾸지 않는다. 지남 판정은 여전히
 * 서버 사유(`hold_overdue`)가 갖는다.
 */
export function holdReviewDueText(
  item: Pick<OpportunityListItem, "hold_review_due_at" | "action_reasons">,
  now: number,
): { text: string; urgent: boolean } {
  const due = holdReviewDue(item, now);
  if (due.state === "unknown") return { text: "기한 미확인", urgent: false };
  if (due.state === "overdue") return { text: "기한 지남", urgent: true };
  const day = kstDayLabel(item.hold_review_due_at);
  return day === null ? { text: "기한 미확인", urgent: false } : { text: `기한 ${day}`, urgent: false };
}
