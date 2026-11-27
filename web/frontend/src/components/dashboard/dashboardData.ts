import type { OpportunityLinkView } from "../../lib/types";
import { remainingDeadlineDays } from "../../lib/deadline";
import { isConfirmedLink, stageOfLink } from "../opportunities/trackingFlow";
import type { LifecycleStage } from "../opportunities/trackingFlow";

const KST_DATE = new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Seoul", year: "numeric", month: "2-digit", day: "2-digit" });
function kstDayIndex(time: number): number {
  const parts = KST_DATE.formatToParts(new Date(time));
  const part = (type: string) => Number(parts.find(item => item.type === type)?.value);
  return Date.UTC(part("year"), part("month") - 1, part("day")) / 86_400_000;
}

/** 누적 업무 패널이 보여 주는 목록 길이. 건수는 `/api/workload`가 따로 낸다(ADR-0067 결정 7). */
export const WORK_PANEL_LIMIT = 5;
/** 보류 기한 지남 목록. 사업 추적의 URL 동기화 이름(`section`·`reason`)을 그대로 쓴다. */
export const HOLD_REVIEW_LIST_PATH = "/opportunities?section=조치 필요&reason=hold_overdue";
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
  /** 마감을 고른 링크의 단계. 단계를 읽지 못하면 `null`이다. */
  stage: LifecycleStage | null;
  /** 마감을 고른 링크의 예산. 서버가 주지 않았으면 `null`이다. */
  budget: number | null;
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
  const days = remainingDeadlineDays(new Date(best.at), new Date(now));
  return { kind, deadlineAt: best.link.deadline_at, days, urgent: days <= DEADLINE_URGENT_DAYS, stage, budget: best.link.budget };
}
