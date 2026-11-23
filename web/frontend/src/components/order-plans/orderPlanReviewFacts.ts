import type { OrderPlanStage1Status, OrderPlanStage2Status } from "../../lib/types";
import type { ORDER_PLAN_UNJUDGED_KIND_LABEL } from "../../lib/glossary";

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

