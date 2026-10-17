import { formatCompactPrice } from "./deadline";
import type {
  BriefingDeadlineKind,
  BriefingItemView,
  BriefingReaction,
  BriefingReason,
  BriefingStage,
  BriefingVerdictDisplay,
} from "./types";

/*
 * `/briefing` 화면의 순수 도우미(RL-01 spec "화면 `/briefing`").
 *
 * 서버가 준 항목을 이름 붙이고 세기만 한다. 판정·점수·정책을 만들거나 다시 계산하지 않는다:
 * 응답에 `score`·`policy_sha256`이 없으므로 화면이 알 방법도 없다. 모르는 코드는 숨기지
 * 않고 그대로 보여 준다(AGENTS "auto_preparation_reason" 규칙과 같다).
 */

/** 뷰 탭 = `reaction` 필터. 주소의 `?view=` 값이다. */
export const BRIEFING_TABS = ["pending", "accepted", "ignored", "later"] as const;
export type BriefingTab = (typeof BRIEFING_TABS)[number];

export const BRIEFING_TAB_LABEL: Record<BriefingTab, string> = {
  pending: "반응 대기",
  accepted: "채택",
  ignored: "무시",
  later: "나중에",
};

export const BRIEFING_TAB_REACTION: Record<BriefingTab, BriefingReaction> = {
  pending: "대기",
  accepted: "채택",
  ignored: "무시",
  later: "나중에",
};

/** 허용값 밖의 `?view=`는 없는 값으로 본다(호출자가 기본 탭을 정한다). */
export function parseBriefingTab(raw: string | null): BriefingTab | null {
  return (BRIEFING_TABS as readonly string[]).includes(raw ?? "") ? (raw as BriefingTab) : null;
}

export function tabOfReaction(reaction: BriefingReaction): BriefingTab {
  return BRIEFING_TABS.find((tab) => BRIEFING_TAB_REACTION[tab] === reaction) ?? "pending";
}

/** 탭 건수는 추천 항목의 `reaction`을 클라이언트가 센다(추적 변화 행은 반응이 없다). */
export function countByTab(items: readonly BriefingItemView[]): Record<BriefingTab, number> {
  const counts: Record<BriefingTab, number> = { pending: 0, accepted: 0, ignored: 0, later: 0 };
  for (const item of items) {
    if (item.reaction === null) continue;
    counts[tabOfReaction(item.reaction)] += 1;
  }
  return counts;
}

export const BRIEFING_STAGE_LABEL: Record<BriefingStage, string> = {
  pre_spec: "사전규격",
  bid_notice: "입찰공고",
  order_plan: "발주계획",
};

export function stageLabel(stage: string): string {
  return (BRIEFING_STAGE_LABEL as Record<string, string>)[stage] ?? stage;
}

/** 판정 칸 pill의 색 의미. 모르는 값은 muted로 두고 글자는 그대로 보여 준다. */
export type VerdictTone = "muted" | "warning" | "success" | "error";

export function verdictTone(verdict: BriefingVerdictDisplay | string): VerdictTone {
  // 판정 이름(RL-03 v2): 진행 가능 success · 조건부 진행 warning · 진행 어려움 error · 판단 불가 중립.
  if (verdict === "진행 가능") return "success";
  if (verdict === "진행 어려움") return "error";
  if (verdict === "조건부 진행") return "warning";
  // 재검토 중·마감 임박 = 사람이 먼저 봐야 하는 변화(warning), 그 밖은 중립이다.
  return verdict === "재검토 중" || verdict === "마감 임박" ? "warning" : "muted";
}

const CHANGE_FIELD_LABEL: Record<string, string> = {
  deadline_at: "마감",
  title: "제목",
  budget: "예산",
  estimated_price: "추정가격",
  method: "계약방법",
  deadline_reminder: "마감 임박",
};

export function changeFieldLabel(field: string): string {
  return CHANGE_FIELD_LABEL[field] ?? field;
}

export function reasonLabel(reason: BriefingReason): string {
  switch (reason.kind) {
    case "keyword":
      return reason.text ? `키워드 · ${reason.text}` : "키워드";
    case "similar_project":
      return typeof reason.count === "number" ? `비슷한 실적 ${reason.count}건` : "비슷한 실적";
    case "repeat_agency":
      return reason.text ? `기관 거래 이력 · ${reason.text}` : "기관 거래 이력";
    default:
      // 모르는 종류는 숨기지 않는다.
      return (reason as { text?: string | null; kind: string }).text ?? (reason as { kind: string }).kind;
  }
}

// ---------------------------------------------------------------------------
// 날짜. 브리핑 날짜와 마감은 모두 한국 시간(KST) 기준이다.

const DATE_ONLY = /^(\d{4})-(\d{2})-(\d{2})$/;
const WEEKDAY = ["일", "월", "화", "수", "목", "금", "토"] as const;
const DAY_MS = 86_400_000;
const KST_OFFSET_MS = 9 * 3_600_000;

export function isIsoDate(value: string): boolean {
  const match = DATE_ONLY.exec(value);
  if (!match) return false;
  const probe = new Date(Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3])));
  return probe.getUTCFullYear() === Number(match[1])
    && probe.getUTCMonth() === Number(match[2]) - 1
    && probe.getUTCDate() === Number(match[3]);
}

function utcDay(value: string): Date {
  const match = DATE_ONLY.exec(value);
  if (!match) throw new Error("invalid ISO date");
  return new Date(Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3])));
}

/** `2026-10-16` → `10월 16일 (금)`. 시각대 계산 없이 날짜 문자열만 쓴다. */
export function formatBriefingDate(value: string): string {
  if (!isIsoDate(value)) return value;
  const day = utcDay(value);
  return `${day.getUTCMonth() + 1}월 ${day.getUTCDate()}일 (${WEEKDAY[day.getUTCDay()]})`;
}

/** 직전 평일(월 → 지난 금). 브리핑은 평일에만 만들어진다. */
export function previousWeekday(value: string): string | null {
  if (!isIsoDate(value)) return null;
  const day = utcDay(value);
  do {
    day.setTime(day.getTime() - DAY_MS);
  } while (day.getUTCDay() === 0 || day.getUTCDay() === 6);
  return day.toISOString().slice(0, 10);
}

function kst(value: Date): Date {
  // UTC getter로 한국 시각을 읽기 위해 9시간을 더한 가짜 UTC 시각이다.
  return new Date(value.getTime() + KST_OFFSET_MS);
}

function kstDayNumber(value: Date): number {
  const shifted = kst(value);
  return Math.floor(Date.UTC(shifted.getUTCFullYear(), shifted.getUTCMonth(), shifted.getUTCDate()) / DAY_MS);
}

/** 마감까지 남은 한국 달력 날수. 오늘이면 0, 지났으면 음수, 읽을 수 없으면 `null`. */
export function daysUntil(deadlineAt: string | null, now: Date = new Date()): number | null {
  if (!deadlineAt) return null;
  const deadline = new Date(deadlineAt);
  if (Number.isNaN(deadline.getTime())) return null;
  return kstDayNumber(deadline) - kstDayNumber(now);
}

/** D-n 강조는 7일 이내만이다(spec "마감 D-n[7일 이내만 강조]"). */
export const DEADLINE_EMPHASIS_DAYS = 7;

export function deadlineDayLabel(days: number): string {
  if (days < 0) return "마감 지남";
  return days === 0 ? "D-day" : `D-${days}`;
}

function shortDate(value: Date): string {
  const shifted = kst(value);
  return `${String(shifted.getUTCMonth() + 1).padStart(2, "0")}.${String(shifted.getUTCDate()).padStart(2, "0")}`;
}

function clockTime(value: Date): string {
  const shifted = kst(value);
  return `${String(shifted.getUTCHours()).padStart(2, "0")}:${String(shifted.getUTCMinutes()).padStart(2, "0")}`;
}

/** `10월 20일 (화) 18:00`. 분까지만 적고 초는 쓰지 않는다. */
function longDateTime(value: Date): string {
  const shifted = kst(value);
  return `${shifted.getUTCMonth() + 1}월 ${shifted.getUTCDate()}일 (${WEEKDAY[shifted.getUTCDay()]}) ${clockTime(value)}`;
}

/** `2026-11` → `11월 발주 예정`. 형식이 다르면 원문을 그대로 둔다. */
export function plannedMonthLabel(plannedMonth: string | null): string {
  const match = /^(\d{4})-(\d{2})$/.exec(plannedMonth ?? "");
  if (!match) return plannedMonth ? `${plannedMonth} 발주 예정` : "발주 예정월 미확인";
  return `${Number(match[2])}월 발주 예정`;
}

const DEADLINE_KIND_LABEL: Record<BriefingDeadlineKind, string> = {
  bid_close: "입찰 마감",
  opinion_close: "의견 마감",
  planned_month: "발주 예정",
};

export interface DeadlineCell {
  /** 첫 줄(D-n 또는 n월 발주 예정). */
  main: string;
  /** 둘째 줄(날짜·마감 종류). 없으면 `null`이다. */
  sub: string | null;
  /** 7일 이내(지난 마감 제외)일 때만 true. 색만이 아니라 글자(D-n)가 함께 전한다. */
  urgent: boolean;
  /** 남은 날수. D-n이 없는 항목은 `null`이다. */
  days: number | null;
}

export function deadlineCell(item: BriefingItemView, now: Date = new Date()): DeadlineCell {
  if (item.deadline_kind === "planned_month" || (item.deadline_at === null && item.planned_month !== null)) {
    return { main: plannedMonthLabel(item.planned_month), sub: null, urgent: false, days: null };
  }
  const days = daysUntil(item.deadline_at, now);
  if (days === null || item.deadline_at === null) {
    return { main: "마감 미확인", sub: null, urgent: false, days: null };
  }
  const kind = item.deadline_kind === "opinion_close" ? "의견 마감" : null;
  const date = shortDate(new Date(item.deadline_at));
  return {
    main: deadlineDayLabel(days),
    sub: kind ? `${date} · ${kind}` : date,
    urgent: days >= 0 && days <= DEADLINE_EMPHASIS_DAYS,
    days,
  };
}

/** 피크 보조 줄의 마감 문구: `10월 20일 (화) 18:00 입찰 마감` 또는 `11월 발주 예정`. */
export function deadlineDetail(item: BriefingItemView): string {
  if (item.deadline_kind === "planned_month" || (item.deadline_at === null && item.planned_month !== null)) {
    return plannedMonthLabel(item.planned_month);
  }
  if (!item.deadline_at) return "마감 미확인";
  const parsed = new Date(item.deadline_at);
  if (Number.isNaN(parsed.getTime())) return "마감 미확인";
  const kind = item.deadline_kind ? DEADLINE_KIND_LABEL[item.deadline_kind] : "마감";
  return `${longDateTime(parsed)} ${kind}`;
}

/** 금액이 없으면 0이 아니라 `금액 미공개`다(값 없음과 실제 0은 다르다). */
export function amountText(amountKrw: number | null): string {
  return amountKrw === null ? "금액 미공개" : formatCompactPrice(amountKrw);
}

export function agencyText(agency: string): string {
  return agency.trim() ? agency : "기관 미확인";
}

export function itemSubline(item: BriefingItemView): string {
  return `${agencyText(item.agency)} · ${amountText(item.amount_krw)}`;
}

// ---------------------------------------------------------------------------
// 반응 기록 한 줄: `김담당이 채택 · 08:41`

function subjectParticle(name: string): string | null {
  const last = name.slice(-1).charCodeAt(0);
  if (last >= 0xac00 && last <= 0xd7a3) return (last - 0xac00) % 28 === 0 ? "가" : "이";
  return null;
}

export function reactionRecord(item: BriefingItemView): string {
  if (item.reaction === null) return "";
  if (!item.reacted_by || !item.reacted_at) return "아직 반응이 없습니다";
  const at = new Date(item.reacted_at);
  const time = Number.isNaN(at.getTime()) ? null : clockTime(at);
  const via = item.reacted_via === "slack" ? "Slack" : null;
  const name = item.reacted_by.trim();
  const particle = subjectParticle(name);
  const action = item.reaction === "대기" ? "반응을 취소" : item.reaction;
  const head = particle ? `${name}${particle} ${action}` : `${name} · ${action}`;
  return [head, time, via].filter((part): part is string => part !== null).join(" · ");
}

/** 레코드 링크는 같은 사이트의 절대 경로만 허용한다(`//host`·`scheme:`는 거절). */
export function safeRecordPath(path: string): string | null {
  return /^\/(?!\/)[^\s]*$/.test(path) ? path : null;
}
