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
 * 1차 선별 결과의 문구(0921 명세 §3.1). 모델·알고리즘 이름(`BM25`)은 실무 화면에서
 * 쓰지 않고 운영 화면(`/runs`의 `발주계획 선별` 탭)이 진다.
 *
 * 실패·거부·값 없음을 한 문구로 뭉개지 않는다(경고 ④) — 실패는 성공이 아니고,
 * 값이 없는 것은 실패가 아니다.
 */
export function stage1RowLabel(value: OrderPlanStage1Status | null): string {
  if (value === "failed") return "선별 실패";
  if (value === "rejected") return "선별 거부";
  if (value === null) return "선별 결과 없음";
  return `1차 선별 ${orderPlanLabel(ORDER_PLAN_STAGE1_LABEL, value)}`;
}

/**
 * 행·상세에 그릴 1차 선별 배지. `선정`과 `제외`는 그리지 않는다(0921 명세 §3.1).
 *
 * - `선정`은 목록의 거의 모든 행에 붙는 기본값이라 아무것도 구분하지 못한다.
 * - `제외`는 `1차 선별 제외` 보기 탭에 들어온 것 자체가 같은 사실을 말한다.
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
