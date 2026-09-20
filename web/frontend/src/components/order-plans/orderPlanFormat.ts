import type {
  OrderPlanListItem,
  OrderPlanRelevance,
  OrderPlanStage1Status,
  OrderPlanStage2Status,
} from "../../lib/types";

export function formatMoment(value: string | null | undefined): string {
  if (!value) return "미확인";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString("ko-KR");
}

export function textOrUnknown(value: string | null | undefined): string {
  return value && value.trim() ? value : "미확인";
}

export function plannedTiming(year: string | null, month: string | null): string {
  if (year === null && month === null) return "null (계획 시기 미제공)";
  // 실제 수집 값은 월만("09") 또는 연월("2026-09")이다. 같은 연도를
  // 두 번 표시하지 않으며, 서로 다른 연도나 누락값은 추정해 고치지 않는다.
  const monthOnly = year && month && /^\d{4}-\d{2}$/.test(month) && month.startsWith(`${year}-`)
    ? month.slice(5)
    : month;
  return `${year ?? "null"}년 ${monthOnly ?? "null"}월`;
}

/** 상세의 사실 표는 라벨이 따로 있으므로 값만 쓴다. null은 그대로 밝힌다. */
export function budgetValue(value: number | null): string {
  return value === null ? "null (미제공)" : `${value.toLocaleString("ko-KR")}원`;
}

export function stage1RowLabel(value: OrderPlanStage1Status | null): string {
  if (value === "selected") return "BM25 선정";
  if (value === "filtered_out") return "BM25 탈락";
  if (value === "failed") return "BM25 실패";
  if (value === "rejected") return "BM25 거부";
  return "BM25 결과 null";
}

/**
 * 시안과 같은 색 규칙: 실패·거부만 오류 색이고 나머지는 중립이다.
 *
 * 상태를 색으로 구분하지 않는다 — 목록의 거의 모든 행이 `BM25 선정`이라 그 색이 켜져
 * 있으면 화면이 온통 강조색이 되고, 정작 눈에 띄어야 할 실패가 묻힌다. 구분은 라벨이
 * 진다(`BM25 선정`·`BM25 탈락`·`BM25 실패`).
 */
export function stage1BadgeVariant(value: OrderPlanStage1Status | null): "neutral" | "error" {
  if (value === "failed" || value === "rejected") return "error";
  return "neutral";
}

/** stage2_status 5값(not_attempted/success/failed/rejected/unknown)을 그대로 구분한다.
 * relevance가 null이라고 실패·거부·미시도·unknown을 전부 같은 문구로 뭉개지 않는다. */
export function stage2Label(value: OrderPlanStage2Status | null): string {
  if (value === "not_attempted") return "Qwen 미시도";
  if (value === "success") return "Qwen 완료";
  if (value === "failed") return "Qwen 실패";
  if (value === "rejected") return "Qwen 거부";
  if (value === "unknown") return "Qwen unknown";
  return "Qwen 결과 null";
}

/** relevance가 있으면 relevance 문구를, 없으면(null) stage2_status로 이유를 구분해 보여준다.
 * qwen_relevance만 보면 not_attempted·failed·rejected·unknown이 전부 "null"로 뭉개지므로
 * (F1) 행과 신호 세부 탭 양쪽에서 이 함수 하나로 일관되게 표시한다. */
export function qwenRowLabel(item: { qwen_relevance: OrderPlanRelevance | null; stage2_status: OrderPlanStage2Status | null }): string {
  if (item.qwen_relevance === "relevant") return "모델 관련";
  if (item.qwen_relevance === "uncertain") return "모델 판단 보류";
  if (item.qwen_relevance === "not_relevant") return "모델 비관련";
  return stage2Label(item.stage2_status);
}

/** stage1과 같은 규칙이다. 관련성은 한국어 라벨로 구분하고 원래 값은 신호 세부에서 읽는다. */
export function qwenBadgeVariant(item: { qwen_relevance: OrderPlanRelevance | null; stage2_status: OrderPlanStage2Status | null }): "error" | "neutral" {
  if (item.stage2_status === "failed" || item.stage2_status === "rejected") return "error";
  return "neutral";
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
