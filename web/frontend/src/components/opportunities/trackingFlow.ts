import type {
  OpportunityActionReason,
  OpportunityDetailResponse,
  OpportunityLinkView,
  OpportunityListItem,
  OpportunityRecheckEventKind,
  OpportunitySearchStrategy,
  OpportunitySearchTarget,
} from "../../lib/types";
import { describeDeadline, shortDateLabel } from "../../lib/deadline";
import { formatNumber } from "../../lib/format";

/**
 * 사업 추적 화면이 읽는 생애주기 사실.
 *
 * 여기의 함수는 **서버가 준 값만** 읽는다. 구역(`section`)·후보 수
 * (`pending_candidate_link_count`)·미해결 확인 항목 수(`open_blocking_item_count`)는
 * 서버가 계산해 주므로 화면이 다시 판정하지 않는다. 이 파일이 하는 일은 저장된
 * 연결을 시안의 3단계 줄(발주계획·사전규격·입찰공고)과 `다음 확인` 한 줄로
 * 옮기는 표시 변환뿐이다.
 *
 * 지키는 것:
 * - 체크 표시는 **연결 확정**을 뜻한다. 분석 완료나 입찰 승인을 뜻하지 않는다.
 * - 기각된 후보는 확정으로 승격하지 않는다. 이력으로만 남는다.
 * - `검색 미확인`은 "레코드가 없다"가 아니라 "이름 검색으로 못 찾았다"이다.
 * - 확정된 최근 단계는 확정 연결에서만 나온다. 대기 중 후보는 올리지 않는다.
 */

export type LifecycleStage = "발주계획" | "사전규격" | "입찰공고";

export const LIFECYCLE_STAGES: LifecycleStage[] = ["발주계획", "사전규격", "입찰공고"];

/** 연결 하나가 가리키는 생애주기 단계. 단계를 알 수 없으면 null이다. */
export function stageOfLink(link: OpportunityLinkView): LifecycleStage | null {
  if (link.stage === "order_plan") return "발주계획";
  if (link.source_type === "pre_spec") return "사전규격";
  if (link.source_type === "bid_notice") return "입찰공고";
  // `검색 미확인`에는 원천 레코드가 없다. 찾아보기 대상(`search_target_kind`)이 실려
  // 있을 때만 그 단계로 읽고, 없으면 단계를 추정하지 않는다.
  const target = searchTargetKindOf(link);
  if (link.status === "검색 미확인" && target !== null) return SEARCH_TARGET_STAGE[target];
  return null;
}

const SEARCH_TARGET_STAGE: Record<OpportunitySearchTarget, LifecycleStage> = {
  pre_spec: "사전규격",
  bid_notice: "입찰공고",
};

/** 찾아보기 대상의 화면 이름. */
export function searchTargetLabel(target: OpportunitySearchTarget): LifecycleStage {
  return SEARCH_TARGET_STAGE[target];
}

/**
 * `검색 미확인` 행이 어느 찾아보기 대상의 기록인지(spec §3.3 `search_target_kind`).
 *
 * 값이 오면 읽고, 없거나 모르는 값이면 `null`(대상 미확인)로 둔다 — 화면이 대상을
 * 추정해 채우지 않는다.
 */
export function searchTargetKindOf(link: OpportunityLinkView): OpportunitySearchTarget | null {
  const value: unknown = link.search_target_kind;
  return value === "pre_spec" || value === "bid_notice" ? value : null;
}

/** 사람이 기각한 후보. 확정으로 쓰지 않지만 목록에서 숨기지도 않는다. */
export function isRejectedCandidate(link: OpportunityLinkView): boolean {
  return link.human_decision === "rejected";
}

/**
 * 확정 연결. `docs/contracts.md`가 정한 authoritative 조합 그대로다:
 * `(official + 확정)` 또는 `(candidate + 사람 확인 완료 + accepted)`.
 */
export function isConfirmedLink(link: OpportunityLinkView): boolean {
  if (link.link_type === "official") return link.status === "확정";
  return link.status === "사람 확인 완료" && link.human_decision === "accepted";
}

export function isPendingCandidate(link: OpportunityLinkView): boolean {
  return link.link_type === "candidate" && link.status === "후보 확인 대기";
}

export type StageConnection = "공식 연결" | "사람 확인 완료" | "후보 확인 대기" | "검색 미확인" | "사람 확인 병합" | "연결 미확인";

export interface StageView {
  stage: LifecycleStage;
  connection: StageConnection;
  confirmed: boolean;
  candidate: boolean;
}

/** 3단계 줄 하나. 같은 단계에 연결이 여럿이면 확정을 우선해 상태를 정한다. */
export function stageViews(links: readonly OpportunityLinkView[]): StageView[] {
  const visibleSearches = new Set(visibleUnconfirmedSearches(links));
  return LIFECYCLE_STAGES.map((stage) => {
    const inStage = links.filter((link) => stageOfLink(link) === stage
      && !isRejectedCandidate(link)
      && (link.status !== "검색 미확인" || visibleSearches.has(link)));
    const confirmed = inStage.find(isConfirmedLink);
    if (confirmed) {
      return {
        stage,
        connection: confirmed.link_type === "official" ? "공식 연결" : "사람 확인 완료",
        confirmed: true,
        candidate: false,
      };
    }
    if (inStage.some(isPendingCandidate)) {
      return { stage, connection: "후보 확인 대기", confirmed: false, candidate: true };
    }
    if (inStage.some((link) => link.status === "검색 미확인")) {
      return { stage, connection: "검색 미확인", confirmed: false, candidate: false };
    }
    return { stage, connection: "연결 미확인", confirmed: false, candidate: false };
  });
}

/** 확정된 최근 단계. 확정 연결이 하나도 없으면 `확인 전`이다. */
export function latestConfirmedStage(links: readonly OpportunityLinkView[]): LifecycleStage | "확인 전" {
  const confirmed = stageViews(links).filter((view) => view.confirmed);
  return confirmed.length > 0 ? confirmed[confirmed.length - 1].stage : "확인 전";
}

export type NextCheckKey =
  | "tracking_decision"
  | "candidate_link"
  | "merge_confirmation"
  | "recheck"
  | "hold_overdue"
  | "blocking_item"
  | "search_unconfirmed"
  | "hold_reason"
  | "end_reason"
  | "linked_records";

export interface NextCheck {
  key: NextCheckKey;
  label: string;
  /** 상세에서 한 문단으로 읽히는 설명. 없는 사실을 채우지 않는다. */
  description: string;
}

type TrackingFacts = Pick<
  OpportunityListItem,
  | "tracking_status"
  | "tracking_reason"
  | "recheck_signal"
  | "pending_candidate_link_count"
  | "open_blocking_item_count"
  | "links"
  | "action_reasons"
>;

// ---------------------------------------------------------------------------
// 조치 사유 (spec §7.1). 사유는 서버가 모든 행에 계산해 준다. 화면은 이름과 순서만 정한다.

/** 칩·필터에 나열하는 순서(spec §11.1의 표기 순서). */
export const ACTION_REASON_ORDER: readonly OpportunityActionReason[] = [
  "new_link",
  "candidate_pending",
  "merge_confirmation",
  "blocking_item",
  "hold_overdue",
];

/** 행의 주 행동 하나를 고르는 우선순위. 앞의 사유가 있으면 뒤는 칩으로만 남는다. */
export const ACTION_REASON_PRIORITY: readonly OpportunityActionReason[] = [
  "new_link",
  "merge_confirmation",
  "candidate_pending",
  "hold_overdue",
  "blocking_item",
];

const ACTION_REASON_LABELS: Record<OpportunityActionReason, string> = {
  new_link: "새 공고",
  candidate_pending: "후보 확인",
  merge_confirmation: "병합 확인",
  blocking_item: "확인 항목",
  hold_overdue: "보류 기한 지남",
};

/** 사유 코드의 이름. 모르는 코드는 바꾸거나 숨기지 않고 그대로 보여 준다. */
export function actionReasonLabel(code: string): string {
  return (ACTION_REASON_LABELS as Record<string, string | undefined>)[code] ?? code;
}

/** 서버가 준 사유 배열. 오래된 응답처럼 필드가 없으면 빈 배열이며 사유를 계산해 채우지 않는다. */
export function actionReasonsOf(item: Pick<OpportunityListItem, "action_reasons">): readonly OpportunityActionReason[] {
  return Array.isArray(item.action_reasons) ? item.action_reasons : [];
}

/** 우선순위가 가장 높은 사유 하나. */
export function topActionReason(item: Pick<OpportunityListItem, "action_reasons">): OpportunityActionReason | null {
  const present = actionReasonsOf(item);
  return ACTION_REASON_PRIORITY.find((code) => present.includes(code)) ?? null;
}

/** 목록 행의 주 행동이 상세에서 여는 자리. */
export type OpportunityDetailIntent =
  | { kind: "checks" }
  | { kind: "candidate"; linkId: number | null }
  | { kind: "tracking" };

export interface RowPrimaryAction {
  reason: OpportunityActionReason;
  label: string;
  intent: OpportunityDetailIntent;
}

/** 사유에 맞는 대기 후보 하나. 병합 확인과 이름 검색 후보를 섞지 않는다. */
export function pendingCandidateFor(
  links: readonly OpportunityLinkView[],
  reason: "candidate_pending" | "merge_confirmation",
): OpportunityLinkView | null {
  const pending = links.filter(isPendingCandidate);
  const matched = pending.find((link) => (link.search_strategy === "merge_confirmation") === (reason === "merge_confirmation"));
  return matched ?? pending[0] ?? null;
}

/** 행 하나의 주 행동(spec §11.1). 사유가 없으면 행동을 만들지 않는다. */
export function rowPrimaryAction(item: Pick<OpportunityListItem, "action_reasons" | "links">): RowPrimaryAction | null {
  const reason = topActionReason(item);
  if (reason === "new_link") return { reason, label: "확인", intent: { kind: "checks" } };
  if (reason === "merge_confirmation" || reason === "candidate_pending") {
    return { reason, label: "후보 확인", intent: { kind: "candidate", linkId: pendingCandidateFor(item.links, reason)?.id ?? null } };
  }
  if (reason === "hold_overdue") return { reason, label: "재검토", intent: { kind: "tracking" } };
  if (reason === "blocking_item") return { reason, label: "확인 사항 열기", intent: { kind: "checks" } };
  return null;
}

// ---------------------------------------------------------------------------
// 보류 재검토 기한 (spec §7.3). 기한은 서버 값이고 화면은 한국 시간 날짜 차이만 적는다.

const KST_DATE = new Intl.DateTimeFormat("en-CA", {
  timeZone: "Asia/Seoul",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
});

function kstDayNumber(instant: Date): number {
  const parts = KST_DATE.formatToParts(instant);
  const part = (type: "year" | "month" | "day") => Number(parts.find((entry) => entry.type === type)?.value);
  return Date.UTC(part("year"), part("month") - 1, part("day")) / 86_400_000;
}

/** 기한 날짜 − 오늘(한국 시간 달력 기준). 값이 없거나 읽을 수 없으면 null이다. */
export function holdReviewDayDelta(dueAt: string | null, now: Date = new Date()): number | null {
  if (!dueAt) return null;
  const due = new Date(dueAt);
  if (Number.isNaN(due.getTime())) return null;
  return kstDayNumber(due) - kstDayNumber(now);
}

/**
 * 행에 붙일 보류 기한 표기. `hold_overdue`가 있으면 `보류 기한 지남 D+n`(사유 칩),
 * 보류 중이고 기한이 남았으면 `보류 기한 D-n`(중립 캡션)이다. 기한 값이 없으면
 * 날짜를 만들어 내지 않는다.
 */
export function holdReviewText(
  item: Pick<OpportunityListItem, "action_reasons" | "hold_review_due_at" | "tracking_status">,
  now: Date = new Date(),
): string | null {
  const delta = holdReviewDayDelta(item.hold_review_due_at, now);
  if (actionReasonsOf(item).includes("hold_overdue")) {
    return delta === null ? "보류 기한 지남" : `보류 기한 지남 D+${-delta}`;
  }
  if (item.tracking_status !== "보류" || delta === null) return null;
  return delta >= 0 ? `보류 기한 D-${delta}` : `보류 기한 D+${-delta}`;
}

// ---------------------------------------------------------------------------
// 찾아보기 전략 (spec §4.1). 저장된 코드를 바꾸지 않고 이름만 붙인다.

const SEARCH_STRATEGY_LABELS: Record<OpportunitySearchStrategy, string> = {
  full: "전체 이름 일치",
  breaking_split: "구분자 분할 일치",
  normalized: "정규화 이름 일치",
  longest_fragment: "가장 긴 조각 일치",
  prefix12: "앞 12자 일치",
  merge_confirmation: "공식 번호 병합 확인",
};

export function searchStrategyLabel(strategy: string | null): string {
  if (!strategy) return "미확인";
  return (SEARCH_STRATEGY_LABELS as Record<string, string | undefined>)[strategy] ?? strategy;
}

/** 기관 일치 여부. `null`은 비교하지 않았거나 모르는 것이며 불일치가 아니다. */
export function agencyMatchLabel(value: boolean | null): string {
  if (value === true) return "기관 일치";
  if (value === false) return "기관 불일치";
  return "기관 일치 미확인";
}

// ---------------------------------------------------------------------------
// 시각 비교. `Date`는 밀리초까지만 읽으므로 마이크로초는 문자열에서 따로 읽는다.

function instantKey(value: string | null): [number, number] | null {
  if (!value) return null;
  const ms = Date.parse(value);
  if (Number.isNaN(ms)) return null;
  const fraction = /T\d{2}:\d{2}:\d{2}\.(\d+)/.exec(value)?.[1] ?? "";
  return [ms, Number(fraction.slice(3, 6).padEnd(3, "0"))];
}

/** 오름차순 비교. 읽을 수 없는 값·`null`은 가장 이르다. */
export function compareInstants(a: string | null, b: string | null): number {
  const left = instantKey(a);
  const right = instantKey(b);
  if (left === null || right === null) return left === right ? 0 : left === null ? -1 : 1;
  return left[0] - right[0] || left[1] - right[1];
}

/**
 * 화면에 남길 `검색 미확인` 기록.
 *
 * 찾아보기 대상마다 가장 최근 기록 하나만 남기고, 같은 대상에서 그보다 나중에 찾은
 * 후보가 있으면 그 기록은 지난 검색이므로 숨긴다(`last_searched_at` 비교). 대상을
 * 알 수 없는 기록은 한 묶음으로 두고 후보와 비교하지 않는다 — 대상을 추정하지 않는다.
 */
export function visibleUnconfirmedSearches(links: readonly OpportunityLinkView[]): OpportunityLinkView[] {
  const newest = new Map<string, OpportunityLinkView>();
  for (const link of links) {
    if (link.status !== "검색 미확인") continue;
    const key = searchTargetKindOf(link) ?? "unknown";
    const current = newest.get(key);
    const order = current ? compareInstants(link.last_searched_at, current.last_searched_at) : 1;
    if (!current || order > 0 || (order === 0 && link.id > current.id)) newest.set(key, link);
  }
  const kept = new Set(
    [...newest.values()].filter((search) => {
      const target = searchTargetKindOf(search);
      if (target === null) return true;
      return !links.some((other) => other.link_type === "candidate"
        && other.status !== "검색 미확인"
        && other.source_type === target
        && compareInstants(other.last_searched_at, search.last_searched_at) > 0);
    }),
  );
  return links.filter((link) => kept.has(link));
}

/** 재검토 신호 이력 이벤트의 이름(spec §6.3). 모르는 코드는 그대로 둔다. */
export function recheckEventLabel(kind: OpportunityRecheckEventKind | string): string {
  if (kind === "created") return "신호 생성";
  if (kind === "acknowledged") return "확인 완료";
  if (kind === "cleared_by_decision") return "결정 저장으로 해제";
  return kind;
}

/**
 * 다음 확인 하나.
 *
 * 여러 개를 나열하면 무엇부터 할지 화면이 답하지 못한다. 위에서부터 처음 맞는
 * 하나에서 멈춘다. 사유가 있으면 서버가 준 사유를 행의 주 행동과 같은 우선순위로
 * 읽는다(`ACTION_REASON_PRIORITY`).
 */
export function nextCheckOf(item: TrackingFacts): NextCheck {
  if (item.tracking_status === "미선택") {
    return {
      key: "tracking_decision",
      label: "추적 결정",
      description: "아직 추적 여부를 선택하지 않았습니다. 연결된 공고를 읽고 추적 범위를 정해 주세요.",
    };
  }
  const reason = topActionReason(item);
  if (reason === "new_link") {
    return {
      key: "recheck",
      label: "새 공고 재검토",
      description: "새 공식 레코드가 연결되어 재검토 신호가 남아 있습니다. 공고 내용과 기존 검토 내용을 확인해 주세요.",
    };
  }
  if (reason === "merge_confirmation") {
    return {
      key: "merge_confirmation",
      label: "병합 확인",
      description: "공식 번호로 이어진 레코드가 사람이 고른 추적 상태를 가진 다른 사업기회에 있어 자동으로 병합하지 않았습니다. 같은 사업인지 확인해 주세요.",
    };
  }
  if (reason === "candidate_pending") {
    return {
      key: "candidate_link",
      label: "연결 후보 확인",
      description: "공식 통합번호가 아니라 이름 검색으로 찾은 후보입니다. 같은 사업인지 확인하면 사업 흐름에 연결할 수 있습니다.",
    };
  }
  if (reason === "hold_overdue") {
    return {
      key: "hold_overdue",
      label: "보류 재검토",
      description: "보류로 저장한 뒤 재검토 기한이 지났습니다. 추적 상태를 다시 정해 주세요. 보류는 자동으로 풀리지 않습니다.",
    };
  }
  if (reason === "blocking_item") {
    return {
      key: "blocking_item",
      label: "확인 항목 답변",
      description: "연결된 공고의 blocking 확인 항목에 담당자 답변이 없습니다. 원문에서 확인한 사실을 남겨 주세요.",
    };
  }
  if (visibleUnconfirmedSearches(item.links).length > 0) {
    return {
      key: "search_unconfirmed",
      label: "연결 근거 확인",
      description: "이름 검색에서 레코드를 찾지 못했습니다. 레코드가 없다는 뜻은 아닙니다.",
    };
  }
  if (item.tracking_status === "보류") {
    return {
      key: "hold_reason",
      label: "보류 사유 확인",
      description: item.tracking_reason?.trim() || "보류로 저장돼 있지만 기록된 사유가 없습니다.",
    };
  }
  if (item.tracking_status === "종료") {
    return {
      key: "end_reason",
      label: "종료 사유 확인",
      description: item.tracking_reason?.trim() || "종료로 저장돼 있지만 기록된 사유가 없습니다.",
    };
  }
  return {
    key: "linked_records",
    label: "연결 공고 확인",
    description: "현재 연결된 공고와 추적 결정을 확인할 수 있습니다.",
  };
}

/** 행 오른쪽 열의 보조 한 줄. 숫자는 서버가 센 값만 쓰고 주 행동과 같은 사유를 말한다. */
export function nextCheckNote(item: TrackingFacts & { id: number }): string {
  const reason = topActionReason(item);
  if (reason === "new_link") return "재검토 신호";
  if ((reason === "merge_confirmation" || reason === "candidate_pending") && item.pending_candidate_link_count > 0) {
    return `후보 ${item.pending_candidate_link_count}건`;
  }
  if (reason === "blocking_item" && item.open_blocking_item_count > 0) return `확인 항목 ${item.open_blocking_item_count}건`;
  return `#${String(item.id).padStart(3, "0")}`;
}

/**
 * 제목·기관은 확정 연결에서 먼저 찾는다. 기각된 후보의 제목을 사업 이름으로
 * 올리지 않기 위해서다. 확정이 없으면 대기 중 후보, 그다음이 그 밖의 기록이다.
 */
function orderedLinks(item: { links: readonly OpportunityLinkView[] }): OpportunityLinkView[] {
  const confirmed = item.links.filter(isConfirmedLink);
  const pending = item.links.filter(isPendingCandidate);
  const rest = item.links.filter((link) => !isConfirmedLink(link) && !isPendingCandidate(link) && !isRejectedCandidate(link));
  const rejected = item.links.filter(isRejectedCandidate);
  return [...confirmed, ...pending, ...rest, ...rejected];
}

export function primaryTitle(item: OpportunityListItem | OpportunityDetailResponse): string {
  const named = orderedLinks(item).find((link) => link.title && link.title.trim());
  return named?.title?.trim() || "제목 미확인";
}

export function primaryAgency(item: OpportunityListItem | OpportunityDetailResponse): string {
  const named = orderedLinks(item).find((link) => link.agency && link.agency.trim());
  return named?.agency?.trim() || "기관 미확인";
}

/**
 * `primaryTitle`·`primaryAgency`가 고르는 것과 같은 대표 링크(F3, spec §6.3).
 * 사업기회 하나에 발주계획·사전규격·입찰공고가 함께 있어도 서버는 "대표 마감"을
 * 고르지 않으므로(계약 §3.2), 화면도 새 선택 규칙을 만들지 않고 제목을 고른
 * 링크를 그대로 예산·마감·발주 예정의 출처로 쓴다.
 */
export function primaryLink(item: OpportunityListItem | OpportunityDetailResponse): OpportunityLinkView | null {
  return orderedLinks(item).find((link) => link.title && link.title.trim()) ?? null;
}

/** 대표 링크의 금액 한 마디. `null`은 서버가 값을 안 준 것이므로(spec §1.1) `예산
 *  미제공`이다 — `formatPrice`의 `추정가격 미제공`은 이 필드의 이름과 다르다. */
function amountSegment(value: number | null): string {
  return value === null ? "예산 미제공" : `${formatNumber(value)}원`;
}

/** 대표 링크가 발주계획일 때의 발주 예정 한 마디. `year`가 없으면 전체를 비운다
 *  (발주 시기를 말할 것이 없다). `month`만 없으면 `월 미제공`으로 연도만 남긴다. */
function orderPlanSegment(year: string | null, month: string | null): string | null {
  if (year === null) return null;
  return month === null ? `발주 예정 ${year}년 · 월 미제공` : `발주 예정 ${year}년 ${month}월`;
}

/** 대표 링크가 사전규격·입찰공고일 때의 마감 한 마디. `describeDeadline`
 *  (`lib/deadline.ts`)이 이미 계산하는 지남·긴급도 판정을 그대로 쓴다. 지나지
 *  않은 마감의 D-day 자체는 그 계산과 같은 식으로 여기서 마저 구한다 —
 *  `describeDeadline`은 7일을 넘으면 목록 두 줄 표시용으로 D-n 없이 날짜만
 *  주지만, 이 한 줄 표기는 항상 종류(`의견 마감`|`입찰 마감`)와 D-n을 함께
 *  적는다. `null`은 서버가 값을 안 준 것이므로(spec §1.1) `마감 미제공`이다. */
function deadlineSegment(kind: "의견 마감" | "입찰 마감", value: string | null): string {
  const deadline = describeDeadline(value);
  if (!value || deadline.urgency === "none") return "마감 미제공";
  if (deadline.urgency === "passed") return `${kind} 지남 · ${shortDateLabel(value)}`;
  const days = Math.ceil((new Date(value).getTime() - Date.now()) / 86_400_000);
  return `${kind} D-${days}`;
}

/**
 * 사업 추적 행의 "사업명 / 발주기관" 줄 끝에 붙는 대표 링크 요약(F3, spec §6.3).
 * 대표 링크가 없으면 붙일 것이 없으므로 `null`이다. 발주계획 링크는 예산·발주
 * 예정을, 사전규격·입찰공고 링크는 예산·마감(의견 마감|입찰 마감)을 적는다.
 * 단계를 알 수 없는 링크(`stageOfLink`가 `null`)는 화면이 지어내지 않고 생략한다.
 */
export function primaryLinkSummary(item: OpportunityListItem | OpportunityDetailResponse): string | null {
  const link = primaryLink(item);
  if (!link) return null;
  const stage = stageOfLink(link);
  if (stage === "발주계획") {
    const parts = [amountSegment(link.budget), orderPlanSegment(link.planned_order_year, link.planned_order_month)];
    return parts.filter((part): part is string => part !== null).join(" · ");
  }
  if (stage === "사전규격" || stage === "입찰공고") {
    const kind = stage === "사전규격" ? "의견 마감" : "입찰 마감";
    return `${amountSegment(link.budget)} · ${deadlineSegment(kind, link.deadline_at)}`;
  }
  return null;
}

/**
 * 연결 하나의 상태를 3단계 줄과 같은 말로 적는다. 저장된 `status`를 다른 뜻으로
 * 바꾸지 않고 `확정`이 공식 번호로 맺어진 관계라는 것만 이름으로 드러낸다.
 */
export function connectionLabel(link: OpportunityLinkView): StageConnection {
  if (link.status === "확정") return link.link_type === "official" ? "공식 연결" : "사람 확인 완료";
  return link.status;
}

// `lib/format.ts`의 `formatMoment`와 통합하지 않는다(U3): 이 함수는 `.`로 이은 조밀한
// 표기(`2026.09.20 06:10`, 초 없음)이고, `lib/format.ts` 쪽은 `Date.toLocaleString`
// 그대로라 초까지 나온다(`2026. 9. 20. 오전 6:10:00`). 출력이 다르므로 값만 옮기고
// 형식은 각자 유지한다.
/** 날짜·시각은 시안과 같은 조밀한 표기로 적는다. 값이 없으면 채우지 않는다. */
export function formatMoment(value: string | null): string {
  if (!value) return "미확인";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  const pad = (part: number) => String(part).padStart(2, "0");
  return `${parsed.getFullYear()}.${pad(parsed.getMonth() + 1)}.${pad(parsed.getDate())} ${pad(parsed.getHours())}:${pad(parsed.getMinutes())}`;
}

/** 연결이 가리키는 실제 원천 화면 route. 없는 화면을 만들어 내지 않는다. */
export function recordRoute(link: OpportunityLinkView): string | null {
  // 발주계획은 별도 상세 route 없이 목록의 우측 pane을 연다. OpportunityLinkView에는
  // source_run_id가 없으므로, 확인되지 않은 회차를 URL에 덧붙이지 않는다.
  if (link.order_plan_id !== null) return `/order-plans?selected=${link.order_plan_id}`;
  if (link.notice_id === null) return null;
  if (link.source_type === "pre_spec") return `/pre-specs/${link.notice_id}`;
  return `/judgments/${link.notice_id}`;
}

/** 링크 버튼의 이름. 화면 이름을 그대로 말한다. */
export function recordRouteLabel(link: OpportunityLinkView): string {
  if (link.order_plan_id !== null) return "발주계획 검토목록 열기";
  if (link.source_type === "pre_spec") return "사전규격 상세 열기";
  return "공고 판정 이력 열기";
}
