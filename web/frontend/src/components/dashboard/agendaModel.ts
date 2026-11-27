import { DECISION_REVIEW_LABELS } from "../bid-delta/labels";
import { remainingDeadlineDays } from "../../lib/deadline";
import { formatActorName } from "../../lib/format";
import type { BidDeltaDecisionQueueItem, OpportunityListItem } from "../../lib/types";
import { LIFECYCLE_STAGES, isConfirmedLink, primaryAgency, primaryTitle, stageOfLink, type LifecycleStage } from "../opportunities/trackingFlow";
import { DEADLINE_URGENT_DAYS, imminentDeadline } from "./dashboardData";

/**
 * 오늘 할 일의 마감 일정(2026-11-27 시안 C2, `docs/specs/1127_today-simplify/`).
 *
 * 마감 임박 추적 건과 최종 Go/No-Go 대기를 **한국 날짜별로** 묶는다. 화면은 서버가 준
 * 링크·대기열 값을 옮겨 적을 뿐이며 새 판정을 만들지 않는다.
 * - 마감은 `imminentDeadline`이 고른 링크 하나(ADR-0067 결정 4)이고, 예산도 그 링크의 값이다.
 * - 단계 진행은 **확정된 연결이 있는 단계**와 지금 마감이 걸린 단계만 표시한다. 연결이 없는
 *   단계를 지났다고 적지 않는다.
 */

export type ChainState = "linked" | "current" | "absent";
export interface ChainStep { key: string; label: string; state: ChainState }

export interface AgendaItem {
  key: string;
  kind: "tracking" | "final";
  to: string;
  title: string;
  agency: string;
  amount: string;
  deadlineAt: string | null;
  /** `의견등록 마감`·`입찰 마감`·`마감 종류 미확인`. */
  deadlineKind: string;
  /** 한국 시각 `HH:MM`. 마감이 없으면 `null`. */
  time: string | null;
  chain: ChainStep[];
  status: string;
  /** 최종 Go/No-Go를 기다리는 상태면 `warning`. */
  statusTone: "neutral" | "warning";
  /** 상태 아래 한 줄(담당자 또는 결정 단계). */
  statusNote: string | null;
}

export interface AgendaDay {
  type: "day";
  key: string;
  /** `11.28` */
  date: string;
  /** `토` */
  weekday: string;
  /** `오늘`·`내일`·`D-n`·`마감 지남` */
  due: string;
  urgent: boolean;
  /** 오늘이면 true. 오늘 마감은 시각이 지나도 오늘 묶음에 남는다. */
  today: boolean;
  items: AgendaItem[];
}
export interface AgendaGap { type: "gap"; key: string; label: string }
export interface AgendaUnknown { type: "unknown"; key: string; items: AgendaItem[] }
export type AgendaEntry = AgendaDay | AgendaGap | AgendaUnknown;

const KST_PARTS = new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Seoul", year: "numeric", month: "2-digit", day: "2-digit" });
const KST_TIME = new Intl.DateTimeFormat("ko-KR", { timeZone: "Asia/Seoul", hour: "2-digit", minute: "2-digit", hourCycle: "h23" });
const WEEKDAYS = ["일", "월", "화", "수", "목", "금", "토"];
const DAY_MS = 86_400_000;

function kstDay(time: number): number {
  const parts = KST_PARTS.formatToParts(new Date(time));
  const part = (type: string) => Number(parts.find(item => item.type === type)?.value);
  return Date.UTC(part("year"), part("month") - 1, part("day")) / DAY_MS;
}

function dayLabel(day: number): string {
  const date = new Date(day * DAY_MS);
  return `${String(date.getUTCMonth() + 1).padStart(2, "0")}.${String(date.getUTCDate()).padStart(2, "0")}`;
}

/** 빈 날 범위. 같은 달이면 뒤쪽 월을 생략한다(`12.01~06`). */
function gapLabel(from: number, to: number): string {
  const left = dayLabel(from), right = dayLabel(to);
  return left.slice(0, 3) === right.slice(0, 3) ? `${left}~${right.slice(3)}` : `${left}~${right}`;
}

/** 원 단위 금액을 `5억 9,200만 원`처럼 줄인다. 만 원 미만은 반올림하며 정확한 값은 상세 화면이 적는다. */
export function compactWon(value: number): string {
  if (!Number.isFinite(value)) return "값 없음";
  if (Math.abs(value) < 10_000) return `${value.toLocaleString("ko-KR")}원`;
  const man = Math.round(value / 10_000);
  const eok = Math.floor(man / 10_000);
  const rest = man % 10_000;
  if (eok === 0) return `${rest.toLocaleString("ko-KR")}만 원`;
  return rest === 0 ? `${eok.toLocaleString("ko-KR")}억 원` : `${eok.toLocaleString("ko-KR")}억 ${rest.toLocaleString("ko-KR")}만 원`;
}

function timeOf(value: string | null): string | null {
  const at = value === null ? Number.NaN : Date.parse(value);
  return Number.isFinite(at) ? KST_TIME.format(new Date(at)) : null;
}

const CURRENT_LABEL: Record<LifecycleStage, string> = {
  발주계획: "발주계획",
  사전규격: "사전규격 의견등록",
  입찰공고: "입찰공고 마감",
};

/** 추적 건의 단계 진행: 처음 연결된 단계부터 입찰공고까지. */
export function trackingChain(item: OpportunityListItem, current: LifecycleStage | null): ChainStep[] {
  const linked = new Set<LifecycleStage>();
  for (const link of item.links) {
    if (!isConfirmedLink(link)) continue;
    const stage = stageOfLink(link);
    if (stage) linked.add(stage);
  }
  const start = LIFECYCLE_STAGES.findIndex(stage => stage === current || linked.has(stage));
  if (start < 0) return [];
  return LIFECYCLE_STAGES.slice(start).map((stage): ChainStep => ({
    key: stage,
    label: stage === current ? CURRENT_LABEL[stage] : stage,
    state: stage === current ? "current" : linked.has(stage) ? "linked" : "absent",
  }));
}

export function trackingAgendaItem(item: OpportunityListItem, now: number, pending?: BidDeltaDecisionQueueItem): AgendaItem {
  const due = imminentDeadline(item, now);
  const actor = formatActorName(item.tracking_selected_by);
  return {
    key: `tracking-${item.id}`,
    kind: "tracking",
    to: `/opportunities/${item.id}`,
    title: primaryTitle(item),
    agency: primaryAgency(item),
    amount: due?.budget == null ? "예산 미제공" : `예산 ${compactWon(due.budget)}`,
    deadlineAt: due?.deadlineAt ?? null,
    deadlineKind: due?.kind ?? "마감 종류 미확인",
    time: timeOf(due?.deadlineAt ?? null),
    chain: trackingChain(item, due?.stage ?? null),
    // 같은 사업이 최종 결정 대기열에도 있으면 한 행으로 합치고 결정 상태를 앞에 적는다.
    // 결정자 이름은 행마다 반복되므로 싣지 않는다(사업기회 기록에 있다). 미리 넣은 에이전트
    // 결정만 `예시 결정`으로 남겨 사람이 한 결정으로 읽히지 않게 한다.
    status: pending ? `Go/No-Go ${pending.review_state ? DECISION_REVIEW_LABELS[pending.review_state] : "상태 미확인"}` : item.tracking_status,
    statusTone: pending ? "warning" : "neutral",
    statusNote: [pending ? item.tracking_status : null, actor?.endsWith("예시 결정") ? "예시 결정" : null].filter(Boolean).join(" · ") || null,
  };
}

export function finalAgendaItem(item: BidDeltaDecisionQueueItem): AgendaItem {
  const estimated = item.estimated_price === null ? Number.NaN : Number(item.estimated_price);
  return {
    key: `final-${item.opportunity_id}`,
    kind: "final",
    to: `/go-no-go?selected=${item.opportunity_id}`,
    title: item.title?.trim() || "제목 미확인",
    agency: item.agency?.trim() || "발주기관 미확인",
    amount: Number.isFinite(estimated) ? `추정가격 ${compactWon(estimated)}` : "추정가격 미제공",
    deadlineAt: item.deadline_at,
    deadlineKind: "입찰 마감",
    time: timeOf(item.deadline_at),
    chain: [
      { key: "입찰공고", label: "입찰공고", state: item.bid_notice_external_id ? "linked" : "absent" },
      { key: "go-no-go", label: "Go/No-Go 결정", state: "current" },
    ],
    status: `Go/No-Go ${item.review_state ? DECISION_REVIEW_LABELS[item.review_state] : "상태 미확인"}`,
    statusTone: "warning",
    statusNote: "최종 결정 대기",
  };
}

function dueText(days: number): string {
  if (days < 0) return "마감 지남";
  if (days === 0) return "오늘";
  return days === 1 ? "내일" : `D-${days}`;
}

export interface AgendaSources {
  items: AgendaItem[];
  /** 최종 결정 대기 중 마감이 이미 지난 건수(받은 목록 안에서). */
  finalPast: number;
  /** 최종 결정 대기 중 창 밖이거나 마감을 받지 못한 건수(받은 목록 안에서). */
  finalOutside: number;
}

/**
 * 추적 건 목록과 최종 결정 대기열을 한 일정으로 합친다. 같은 사업은 한 행이다. 대기열에만 있는
 * 사업은 마감이 창(`windowDays`) 안일 때만 일정에 두고, 지난 것과 창 밖·마감 미제공은 건수로만 센다.
 */
export function mergeAgendaSources(
  tracking: readonly OpportunityListItem[], final: readonly BidDeltaDecisionQueueItem[], now: number, windowDays: number,
): AgendaSources {
  const pending = new Map(final.map(item => [item.opportunity_id, item]));
  const trackingIds = new Set(tracking.map(item => item.id));
  const items = tracking.map(item => trackingAgendaItem(item, now, pending.get(item.id)));
  let finalPast = 0, finalOutside = 0;
  for (const item of final) {
    if (trackingIds.has(item.opportunity_id)) continue;
    const at = item.deadline_at === null ? Number.NaN : Date.parse(item.deadline_at);
    if (!Number.isFinite(at)) { finalOutside += 1; continue; }
    if (at < now) { finalPast += 1; continue; }
    if (remainingDeadlineDays(new Date(at), new Date(now)) > windowDays) { finalOutside += 1; continue; }
    items.push(finalAgendaItem(item));
  }
  return { items, finalPast, finalOutside };
}

/**
 * 날짜별 묶음. 날짜 사이의 빈 날은 한 줄(`gap`)로 접고, 마감을 읽지 못한 항목은 맨 끝
 * `unknown` 묶음에 둔다(지어낸 날짜에 두지 않는다).
 */
export function buildAgenda(items: readonly AgendaItem[], now: number): AgendaEntry[] {
  const byDay = new Map<number, AgendaItem[]>();
  const unknown: AgendaItem[] = [];
  for (const item of items) {
    const at = item.deadlineAt === null ? Number.NaN : Date.parse(item.deadlineAt);
    if (!Number.isFinite(at)) { unknown.push(item); continue; }
    const day = kstDay(at);
    byDay.set(day, [...(byDay.get(day) ?? []), item]);
  }
  const entries: AgendaEntry[] = [];
  let previous: number | null = null;
  for (const day of [...byDay.keys()].sort((a, b) => a - b)) {
    if (previous !== null && day - previous > 1) {
      const from = previous + 1, to = day - 1;
      entries.push({ type: "gap", key: `gap-${from}`, label: from === to ? dayLabel(from) : gapLabel(from, to) });
    }
    const dayItems = (byDay.get(day) ?? []).sort((a, b) => Date.parse(a.deadlineAt ?? "") - Date.parse(b.deadlineAt ?? "") || a.title.localeCompare(b.title, "ko"));
    // 묶음의 D-day는 한국 날짜 차이다. 오늘 마감이 이미 지난 시각이어도 묶음은 `오늘`이다.
    const days = day - kstDay(now);
    entries.push({
      type: "day", key: `day-${day}`, date: dayLabel(day), weekday: WEEKDAYS[new Date(day * DAY_MS).getUTCDay()] ?? "",
      due: dueText(days), urgent: days >= 0 && days <= DEADLINE_URGENT_DAYS, today: days === 0, items: dayItems,
    });
    previous = day;
  }
  if (unknown.length) entries.push({ type: "unknown", key: "unknown", items: unknown });
  return entries;
}
