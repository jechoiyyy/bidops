import type {
  OrderPlanListItem,
  OrderPlanRelevance,
  OrderPlanStage1Status,
  OrderPlanStage2Status,
} from "../../lib/types";
import { formatMoment as formatMomentBase } from "../../lib/format";
import {
  ORDER_PLAN_RELEVANCE_LABEL,
  ORDER_PLAN_STAGE1_LABEL,
  ORDER_PLAN_STAGE2_LABEL,
  ORDER_PLAN_UNJUDGED_KIND_LABEL,
  ORDER_PLAN_UNJUDGED_LABEL,
  orderPlanLabel,
} from "../../lib/glossary";

/** `lib/format.ts`가 정본이다(U3, 중복 통합). 이 화면의 null 문구(`미확인`)만 고정한다. */
export function formatMoment(value: string | null | undefined): string {
  return formatMomentBase(value, "미확인");
}

const KST_DATE_PARTS = new Intl.DateTimeFormat("en-CA", {
  timeZone: "Asia/Seoul",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
});

/**
 * 첫 수집일의 짧은 표기: `MM-DD`, 해가 올해와 다르면 `YYYY-MM-DD`(한국 시간 관측일).
 *
 * `lib/format.ts`의 짧은 표기 둘은 이 자리에 맞지 않는다 — `formatMomentShort`는 시각을
 * 함께 적고 `formatRunRangeShort`는 회차의 수집 기간(이미 KST 날짜 문자열)을 받는다.
 * 여기서 필요한 것은 **timestamp 하나를 KST 날짜로만** 적는 것이라 이 화면이 갖는다.
 * 값이 없으면 지어내지 않고 미확인으로 남긴다.
 */
export function formatKstDateShort(value: string | null | undefined, nullLabel = "미확인"): string {
  if (!value) return nullLabel;
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  const parts = Object.fromEntries(KST_DATE_PARTS.formatToParts(parsed).map((part) => [part.type, part.value])) as
    Record<"year" | "month" | "day", string>;
  const currentYear = KST_DATE_PARTS.formatToParts(new Date()).find((part) => part.type === "year")?.value;
  return parts.year === currentYear
    ? `${parts.month}-${parts.day}`
    : `${parts.year}-${parts.month}-${parts.day}`;
}

export function textOrUnknown(value: string | null | undefined): string {
  return value && value.trim() ? value : "미확인";
}

/**
 * 발주 예정 시기. 실제 수집 값은 월만("09") 또는 연월("2026-09")이다. 같은 연도를
 * 두 번 표시하지 않고, 빠진 쪽은 다른 값에서 추정하지 않으며 영문 `null` 토큰은
 * 표시에서 뺀다(U3, spec §1.1 — `OrderPlanCandidatesSection.plannedOrderLabel`과
 * 같은 규칙).
 */
export function plannedTiming(year: string | null, month: string | null): string {
  if (year === null && month === null) return "발주 시기 미제공";
  const monthOnly = year && month && /^\d{4}-\d{2}$/.test(month) && month.startsWith(`${year}-`)
    ? month.slice(5)
    : month;
  if (year === null) return `연도 미확인 · ${monthOnly}월`;
  if (monthOnly === null) return `${year}년 · 월 미제공`;
  return `${year}년 ${monthOnly}월`;
}

/** 상세의 사실 표는 라벨이 따로 있으므로 값만 쓴다. null은 서버가 값을 주지 않은
 * 것이므로 `미제공`이다(U3, spec §1.1). */
export function budgetValue(value: number | null): string {
  return value === null ? "예산 미제공" : `${value.toLocaleString("ko-KR")}원`;
}

/**
 * 상세 전용 값(상세 응답만 싣는 값)의 세 가지 빈 상태를 구분한다(spec §1.1).
 *
 * - `불러오는 중`: 아직 상세 응답이 없다. 값이 없다는 뜻이 아니다.
 * - `미확인`: 상세 조회가 실패해 **확인하지 못했다**. `미제공`으로 낮추지 않는다.
 * - `미제공`: 서버가 `null`을 줬다.
 *
 * 세 상태를 한 문구로 뭉개지 않는다 — 서버가 값을 주지 않은 것과 화면이 값을 받지
 * 못한 것은 서로 다른 사실이다.
 */
export function detailFactValue(
  value: string | null | undefined,
  /** 목록이 이미 준 값(계약방법 등)은 기다릴 것이 없으므로 기본값 그대로 쓴다. */
  state: { pending: boolean; failed: boolean } = { pending: false, failed: false },
): string {
  if (state.pending) return "불러오는 중";
  if (state.failed) return "미확인";
  return value && value.trim() ? value : "미제공";
}

/**
 * 공고 게시 여부. 수집 원문 `ntceNticeYn`의 `Y`/`N`이며 bool이 아니다(contracts.md
 * "발주계획 목록·상세 실무 field"). `null`은 `N`이 아니라 미제공이고, `Y`·`N` 밖의
 * 값은 뜻을 추정하지 않고 원문 그대로 적는다.
 */
export function noticePostedLabel(value: string | null | undefined): string {
  if (value === null || value === undefined) return "미제공";
  const raw = value.trim();
  if (raw === "Y") return "게시됨";
  if (raw === "N") return "아직 없음";
  return raw ? raw : "미제공";
}

/**
 * 행의 추적 결정 칩(M5 ① 승인). 사람이 내린 세 결정(`계속 추적`·`보류`·`종료`)은 값
 * 그대로 보이고, `미선택`과 계약상 값이 없는 경우는 **결정하지 않았다**는 사실로
 * 적는다. 결정 없음은 추적 종료가 아니다.
 *
 * 값이 없는 이유(계약 없음·소유 사업기회 미확인)의 구분은 상세 pane이 진다
 * (`trackingStatusLabel`) — 밀집 행은 결정 유무만 말한다.
 */
export function trackingChipLabel(item: Pick<OrderPlanListItem, "tracking">): string {
  const status = item.tracking?.tracking_status ?? null;
  return status === null || status === "미선택" ? "추적 미선택" : status;
}

/**
 * 1차 선별 결과의 문구(0921 명세 §3.1). 모델·알고리즘 이름(`BM25`)은 실무 화면에서
 * 쓰지 않고 운영 화면(`/runs`의 `발주계획 선별` 탭)이 진다.
 *
 * 실패·거부·값 없음을 한 문구로 뭉개지 않는다(경고 ④) — 실패는 성공이 아니고,
 * 값이 없는 것은 실패가 아니다.
 */
export function stage1RowLabel(value: OrderPlanStage1Status | null): string {
  // 2026-11-18 수정안 3B: `선별 실패` 용어를 `모델 미판정(판정 실패)`로 바꿨다.
  if (value === "failed") return `${ORDER_PLAN_UNJUDGED_LABEL}(${ORDER_PLAN_UNJUDGED_KIND_LABEL.judgment_failed})`;
  if (value === "rejected") return "선별 거부";
  if (value === null) return "선별 결과 없음";
  return `1차 선별 ${orderPlanLabel(ORDER_PLAN_STAGE1_LABEL, value)}`;
}

/**
 * 행·상세에 그릴 1차 선별 배지. `선정`과 `제외`는 그리지 않는다(0921 명세 §3.1).
 *
 * - `선정`은 목록의 거의 모든 행에 붙는 기본값이라 아무것도 구분하지 못한다.
 * - `제외`(순위 밖)는 `모델 미판정` 보기 탭이 행마다 `순위 밖` 칩으로 따로 말한다.
 *
 * 남기는 것은 경고뿐이다: 실패·거부·값 없음. 숨기는 것은 기본값 둘이고 실패나
 * 값 없음을 감추지 않는다.
 */
export function stage1BadgeLabel(value: OrderPlanStage1Status | null): string | null {
  if (value === "selected" || value === "filtered_out") return null;
  return stage1RowLabel(value);
}

/**
 * 시안과 같은 색 규칙: 실패·거부만 오류 색이고 나머지는 중립이다.
 *
 * 상태를 색으로 구분하지 않는다 — 값 없음까지 색이 켜지면 화면이 온통 강조색이 되고,
 * 정작 눈에 띄어야 할 실패가 묻힌다. 구분은 라벨이 진다.
 */
export function stage1BadgeVariant(value: OrderPlanStage1Status | null): "neutral" | "error" {
  if (value === "failed" || value === "rejected") return "error";
  return "neutral";
}

/** stage2_status 5값(not_attempted/success/failed/rejected/unknown)을 그대로 구분한다.
 * relevance가 null이라고 실패·거부·미판정·미확인을 전부 같은 문구로 뭉개지 않는다.
 * 모델 이름은 쓰지 않는다(0921 명세 §3.1). */
export function stage2Label(value: OrderPlanStage2Status | null): string {
  // `success`인데 판단이 없는 조합은 계약상 나오지 않는다. 그래도 값이 오면 완료
  // 사실을 그대로 적고 `결과 없음`으로 낮추지 않는다.
  if (value === null) return "모델 결과 없음";
  return orderPlanLabel(ORDER_PLAN_STAGE2_LABEL, value);
}

/**
 * relevance가 있으면 모델 판단을, 없으면(null) stage2_status로 이유를 구분해 보여준다.
 * qwen_relevance만 보면 not_attempted·failed·rejected·unknown이 전부 "값 없음"으로
 * 뭉개지므로(F1) 이 함수 하나로 일관되게 표시한다.
 *
 * 모델 판단에는 `모델 ·` 머리말을 둔다(시안 M3 결정 1 승인) — 머리말이 없으면 `관련`이
 * 사람이 내린 판정(추적 선택·적합성 등급)처럼 읽힌다.
 */
export function qwenRowLabel(item: { qwen_relevance: OrderPlanRelevance | null; stage2_status: OrderPlanStage2Status | null }): string {
  if (item.qwen_relevance !== null) {
    return `모델 · ${orderPlanLabel(ORDER_PLAN_RELEVANCE_LABEL, item.qwen_relevance)}`;
  }
  return stage2Label(item.stage2_status);
}

/**
 * 발주 예정월(`YYYY-MM`). 원문은 `planned_order_month`가 `YYYY-MM`이거나(실데이터) 연도와 따로 온
 * `M`/`MM`이다. 해석할 수 없으면 `null`(미확인)이며 지남으로 보지 않는다.
 */
export function plannedMonthKey(item: { planned_order_year: string | null; planned_order_month: string | null }): string | null {
  const month = item.planned_order_month?.trim() ?? "";
  if (/^\d{4}-(0[1-9]|1[0-2])$/.test(month)) return month;
  const year = item.planned_order_year?.trim() ?? "";
  if (/^\d{4}$/.test(year) && /^\d{1,2}$/.test(month)) {
    const value = Number(month);
    if (value >= 1 && value <= 12) return `${year}-${String(value).padStart(2, "0")}`;
  }
  return null;
}

const KST_MONTH = new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Seoul", year: "numeric", month: "2-digit" });

/** 지금의 한국 시간 달(`YYYY-MM`). */
export function currentKstMonth(now: number): string {
  const parts = KST_MONTH.formatToParts(new Date(now));
  const part = (type: string) => parts.find((entry) => entry.type === type)?.value ?? "";
  return `${part("year")}-${part("month")}`;
}

/**
 * 검토 순서에서 뒤로 보내는 이유. `예정월 지남`: 발주 예정월이 지금 한국 시간 달보다 앞이다(같은 달은
 * 지나지 않았다, 예정월 미확인은 지남이 아니다). `공고 게시됨`: 공고 게시 여부 원문이 `Y`다. 둘 다
 * 표식일 뿐이며 제외·추적 상태를 바꾸지 않는다. 둘 다면 공고 게시가 먼저다(더 확실한 사실).
 */
export type OrderPlanStaleReason = "공고 게시됨" | "예정월 지남";

export function orderPlanStaleReason(
  item: { planned_order_year: string | null; planned_order_month: string | null; notice_posted: string | null },
  nowMonth: string,
): OrderPlanStaleReason | null {
  if (item.notice_posted === "Y") return "공고 게시됨";
  const key = plannedMonthKey(item);
  return key !== null && key < nowMonth ? "예정월 지남" : null;
}

/**
 * `관련`·`불확실` 보기의 검토 순서(2026-11-18). 화면이 이미 범위 전체를 받으므로 브라우저가 정한다.
 * 1) 예정월이 지나지 않았고 공고도 없는 건이 앞, 그 안에서 예정월이 가까운 순(미확인 월은 뒤),
 * 2) 같으면 최근 첫 수집 순, 3) 예정월 지남·공고 게시됨은 뒤에 같은 규칙으로. 같으면 서버 순서를 지킨다.
 */
export function sortForReview<T extends {
  planned_order_year: string | null; planned_order_month: string | null; notice_posted: string | null; first_observed_at: string | null;
}>(items: readonly T[], nowMonth: string): T[] {
  return items
    .map((item, index) => {
      const observed = item.first_observed_at ? Date.parse(item.first_observed_at) : Number.NaN;
      return { item, index, stale: orderPlanStaleReason(item, nowMonth) !== null, month: plannedMonthKey(item), observed: Number.isFinite(observed) ? observed : -Infinity };
    })
    .sort((left, right) =>
      Number(left.stale) - Number(right.stale)
      || (left.stale ? 0 : (left.month ?? "9999-99").localeCompare(right.month ?? "9999-99"))
      || (right.observed === left.observed ? 0 : right.observed > left.observed ? 1 : -1)
      || left.index - right.index)
    .map(({ item }) => item);
}

/**
 * 수집일: `first_observed_at`의 한국 시간 날짜(`YYYY-MM-DD`). 읽을 수 없으면 `null`(미확인)이다.
 * BM25 순위는 **수집일마다** 따로 매겨지므로(일일 실행 하나가 그날 모집단 하나를 줄 세운다)
 * 순위를 비교하려면 이 값이 먼저 같아야 한다.
 */
export function collectionDayKst(value: string | null | undefined): string | null {
  if (!value) return null;
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return null;
  const parts = Object.fromEntries(KST_DATE_PARTS.formatToParts(parsed).map((part) => [part.type, part.value])) as
    Record<"year" | "month" | "day", string>;
  return `${parts.year}-${parts.month}-${parts.day}`;
}

interface RankSortable {
  first_observed_at: string | null;
  stage1_rank: number | null;
}

interface RankSortKey {
  index: number;
  day: string | null;
  rank: number | null;
  observed: number;
}

function rankSortKey(item: RankSortable, index: number): RankSortKey {
  const observed = item.first_observed_at ? Date.parse(item.first_observed_at) : Number.NaN;
  return {
    index,
    day: collectionDayKst(item.first_observed_at),
    rank: item.stage1_rank,
    observed: Number.isFinite(observed) ? observed : -Infinity,
  };
}

/**
 * 수집일 최신 → 그날 BM25 순위 오름차순(순위 없음은 뒤) → 최근 첫 수집 → 서버 순서.
 *
 * 수집일이 다르면 순위를 보지 않는다 — 다른 날의 1위와 2위는 서로 비교할 수 없다. 수집일을
 * 모르는 건(`null`)은 맨 뒤이며 그 안에서도 순위를 비교하지 않는다(같은 날인지 모른다).
 */
function compareByDayThenRank(left: RankSortKey, right: RankSortKey): number {
  if (left.day !== right.day) {
    if (left.day === null) return 1;
    if (right.day === null) return -1;
    return right.day.localeCompare(left.day);
  }
  if (left.day !== null && left.rank !== right.rank) {
    if (left.rank === null) return 1;
    if (right.rank === null) return -1;
    return left.rank - right.rank;
  }
  return (right.observed === left.observed ? 0 : right.observed > left.observed ? 1 : -1)
    || left.index - right.index;
}

/**
 * `불확실`(훑어보기) 보기의 순서(2026-11-18 수정안 3B). 지난 건(예정월 지남·공고 게시됨, `sortForReview`와
 * 같은 규칙)을 뒤로 보낸 뒤, 각 묶음 안에서 수집일 최신 → 그날 BM25 순위순이다.
 */
export function sortForBrowse<T extends RankSortable & {
  planned_order_year: string | null; planned_order_month: string | null; notice_posted: string | null;
}>(items: readonly T[], nowMonth: string): T[] {
  return items
    .map((item, index) => ({ item, stale: orderPlanStaleReason(item, nowMonth) !== null, key: rankSortKey(item, index) }))
    .sort((left, right) => Number(left.stale) - Number(right.stale) || compareByDayThenRank(left.key, right.key))
    .map(({ item }) => item);
}

/** `모델 미판정` 보기의 순서(2026-11-18 수정안 3B): 수집일 최신 → 그날 BM25 순위순. 지난 건을 따로 보내지 않는다. */
export function sortByCollectionRank<T extends RankSortable>(items: readonly T[]): T[] {
  return items
    .map((item, index) => ({ item, key: rankSortKey(item, index) }))
    .sort((left, right) => compareByDayThenRank(left.key, right.key))
    .map(({ item }) => item);
}

/**
 * 판정 실패: 1차 선별 또는 모델 판정이 실패·거부된 건. 상세 필터 `실패·거부만`과 같은 조건이며,
 * 모델이 한 건도 답하지 못한 실행의 행(stage2 `failed`)도 여기 든다.
 */
export function isJudgmentFailure(item: { stage1_status: OrderPlanStage1Status | null; stage2_status: OrderPlanStage2Status | null }): boolean {
  return item.stage1_status === "failed" || item.stage1_status === "rejected"
    || item.stage2_status === "failed" || item.stage2_status === "rejected";
}

/** `모델 미판정` 보기에 드는 두 갈래. 서버가 준 상태만 읽으며 판정을 새로 만들지 않는다. */
export type OrderPlanUnjudgedKind = keyof typeof ORDER_PLAN_UNJUDGED_KIND_LABEL;

/** 판정 실패가 먼저다 — 실패는 사람이 조치할 사실이고 순위 밖은 정책의 절단 결과다. 둘 다 아니면 `null`이다. */
export function orderPlanUnjudgedKind(item: { stage1_status: OrderPlanStage1Status | null; stage2_status: OrderPlanStage2Status | null }): OrderPlanUnjudgedKind | null {
  if (isJudgmentFailure(item)) return "judgment_failed";
  if (item.stage1_status === "filtered_out") return "out_of_rank";
  return null;
}

/**
 * 행의 1차 선별 순위 표기. 실무 화면은 알고리즘 이름(`BM25`)을 쓰지 않으므로(0921 명세 §3.1) `1차 순위`다.
 * 순위가 없으면 지어내지 않고 미제공이다.
 */
export function stage1RankLabel(rank: number | null): string {
  return rank === null ? "1차 순위 미제공" : `1차 순위 ${rank.toLocaleString("ko-KR")}위`;
}

/**
 * 모델 판정이 없는 건(1차 선별 실패·거부, 모델 실패·거부·미확인)에 붙는 표식. 비관련으로 읽지 않는다.
 *
 * 수정안 3B의 `모델 미판정`으로 바꾸지 않았다: 그 말은 이미 모델 처리 상태 `not_attempted`의 라벨이고
 * (`ORDER_PLAN_STAGE2_LABEL`), 이 표식은 `unknown`(정보 부족) 행에도 붙는다. 둘을 같은 말로 쓰면 상태
 * 미확인 행이 미판정으로 읽힌다(F1). `모델 미판정` 보기에서는 이 표식 대신 `순위 밖`·`판정 실패` 칩이 선다.
 */
export const NO_MODEL_JUDGMENT_LABEL = "모델 판정 없음 — 사람 확인";

/**
 * 판정 실행이 이 건을 다뤘는데 모델 판단을 내지 못한 경우다(배치 실패 포함). 실행 계약의
 * `human_review_count`가 사람 검토로 세는 무판정 몫(stage1 실패·거부 + stage2 실패·거부·미확인)과
 * 같은 조건이다. 1차 선별 `제외`나 판정이 아예 없는 범위(`policy_version=null`)는 여기 들지 않는다.
 */
export function hasNoModelJudgment(item: {
  qwen_relevance: OrderPlanRelevance | null;
  stage1_status: OrderPlanStage1Status | null;
  stage2_status: OrderPlanStage2Status | null;
  policy_version: string | null;
}): boolean {
  if (item.policy_version === null || item.qwen_relevance !== null) return false;
  return item.stage1_status === "failed" || item.stage1_status === "rejected"
    || item.stage2_status === "failed" || item.stage2_status === "rejected" || item.stage2_status === "unknown";
}

/** stage1과 같은 규칙이다. 판단은 라벨로 구분하고 색은 실패·거부에만 쓴다. */
export function qwenBadgeVariant(item: { qwen_relevance: OrderPlanRelevance | null; stage2_status: OrderPlanStage2Status | null }): "error" | "neutral" {
  if (item.stage2_status === "failed" || item.stage2_status === "rejected") return "error";
  return "neutral";
}

/** 사람 판단 수정 횟수. 수정본이 하나도 없으면(`0`) 표식을 만들지 않는다. */
export function humanFeedbackBadgeLabel(revision: number | null | undefined): string | null {
  return revision !== null && revision !== undefined && revision >= 1 ? `사람 판단 수정 ${revision}회` : null;
}

/**
 * 추적 결정을 기록할 수 있는지의 세 상태. 서로 바꾸지 않는다.
 *
 * - `contract_missing`: 응답에 `tracking`이 없다. 서버 계약이 아직 없다는 뜻이며
 *   `미선택`이 아니다 (요청안 §7 규칙 3).
 * - `opportunity_missing`: `tracking`이 `null`이다. 이 발주계획을 소유한 사업기회를
 *   확인하지 못했다.
 * - `available`: 추적 상태를 읽었다. 그 값이 `미선택`일 수 있고, 미선택은 종료가 아니다.
 */
export type TrackingAvailability = "available" | "contract_missing" | "opportunity_missing";

export function trackingAvailability(item: OrderPlanListItem | null): TrackingAvailability {
  if (item && !("tracking" in item)) return "contract_missing";
  if (!item || item.tracking == null) return "opportunity_missing";
  return "available";
}

/**
 * 추적 결정(결정 1)의 사유 선택지.
 *
 * 사용자가 승인한 시안(focus-v2)의 목록이 정본이다. 화면은 사유를 자동으로 고르지
 * 않고 사람이 고른 값만 계약에 싣는다. `기타 · 직접 입력`은 값이 아니라 자유 입력을
 * 여는 표식이므로 저장되는 것은 사람이 적은 문장이다.
 */
export const TRACKING_REASONS = [
  "후속 사전규격·공고 확인",
  "사업 방향이 관심 분야와 맞음",
  "예산·시기 추가 확인 필요",
  "세부 과업 확인 후 판단",
  "현재 검토 범위와 맞지 않음",
  "중복·오탐으로 확인",
] as const;

/** 자유 입력을 여는 선택지의 값. 사유 문자열이 아니라 표식이므로 계약에 싣지 않는다. */
export const OTHER_REASON = "other";
