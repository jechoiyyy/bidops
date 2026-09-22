import type { OrderPlanListScope } from "../../lib/types";

/**
 * 목록 응답의 `scope`를 한 줄로 말한다. 누적과 회차는 뜻이 다르므로 같은 문장으로 접지 않는다.
 *
 * 실행 식별자·상태·policy 버전은 실무 화면에서 뺐다(0921 명세 §3.1·§4 — 운영 화면의
 * `발주계획 선별` 탭이 전문 그대로 진다). 남는 것은 **범위를 말하는 사람 말**뿐이다.
 *
 * - 누적: 운영 판정을 발주계획마다 최신 1건씩 모은 범위다. `policy_versions`가 비면
 *   판정이 하나도 없다는 뜻이고, 그것은 비관련이 아니다(경고 ⑤).
 * - 회차: 그 회차의 최신 완료 실행 하나(감사용). 측정 전용 실행이면 반드시 밝힌다(경고 ②).
 * - `null`: 회차에 완료 실행이 없다 — 판정 없음이며 비관련이 아니다.
 */
export function scopeLabel(scope: OrderPlanListScope | null, runLabel?: string | null): string {
  if (scope === null) return "판정 없음 · 이 회차에 완료된 선별 실행이 없습니다";
  if (scope.mode === "cumulative") {
    return scope.policy_versions.length
      ? "누적 · 모든 수집 회차"
      : "누적 · 판정 없음 (운영 선별 판정이 아직 없습니다)";
  }
  const purpose = scope.purpose === "gate_measurement" ? " · 측정 전용 실행" : "";
  return `회차 보기 · ${runLabel ?? "선택한 수집 회차"}${purpose}`;
}

export function statusTone(status: string | null | undefined): "success" | "warning" | "error" | "info" | "neutral" {
  if (status === "성공" || status === "relevant" || status === "selected") return "success";
  if (status === "부분 성공" || status === "uncertain" || status === "실행 중" || status === "중지 요청") return "warning";
  if (status === "실패" || status === "failed" || status === "rejected" || status === "not_relevant") return "error";
  if (status === "대기" || status === "unknown" || status === "not_attempted") return "info";
  return "neutral";
}

/** StatusDot은 success/warning/error/accent/neutral만 지원한다(Badge와 다름). */
export function statusDotVariant(status: string | null | undefined): "success" | "warning" | "error" | "accent" | "neutral" {
  const tone = statusTone(status);
  return tone === "info" ? "accent" : tone;
}
