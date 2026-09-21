import type { OrderPlanListScope } from "../../lib/types";

/**
 * 목록 응답의 `scope`를 한 줄로 말한다. 누적과 회차는 뜻이 다르므로 같은 문장으로 접지 않는다.
 * - 누적: 활성화된 적 있는 policy의 운영 판정을 발주계획마다 최신 1건씩 모은 범위다.
 *   `policy_versions`는 그 범위에 실행이 실제로 있는 버전만이고, 없으면 빈 목록이다.
 * - 회차: 그 회차의 최신 완료 실행 하나(감사용). policy·purpose를 묻지 않으므로 측정 전용 실행이면 밝힌다.
 * - `null`: 회차에 완료 실행이 없다 — 판정 없음이며 비관련이 아니다.
 */
export function scopeLabel(scope: OrderPlanListScope | null): string {
  if (scope === null) return "판정 없음 · 이 회차에 완료된 선별 실행이 없습니다";
  if (scope.mode === "cumulative") {
    return scope.policy_versions.length
      ? `누적 · 판정 policy ${scope.policy_versions.join(", ")}`
      : "누적 · 판정 policy 없음 (활성화된 적 있는 policy의 운영 판정이 아직 없습니다)";
  }
  const purpose = scope.purpose === "gate_measurement" ? " · 측정 전용 실행" : "";
  return `회차 · 실행 ${scope.execution_id.slice(0, 8)} · ${scope.status} · 판정 policy ${scope.policy_version}${purpose}`;
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
