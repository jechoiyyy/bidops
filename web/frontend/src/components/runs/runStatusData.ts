import { useQuery } from "@tanstack/react-query";
import { api } from "../../lib/api";
import type { ScreeningExecutionResponse, ScreeningStatus, ValidationMetric } from "../../lib/types";

/**
 * 실행 상태 화면이 공유하는 조회와 표시 규칙.
 *
 * 요약 한 줄과 회차 목록이 같은 실행 목록을 읽는다. 두 곳이 각자 조회하면
 * 같은 사실을 두 번 받고, 회차마다 실행을 하나씩 조회하면 N+1이 된다. 그래서
 * **한 번, 한계를 정해** 받고 그 한계를 화면이 직접 말한다
 * (IMPLEMENTATION-CONTRACT §상태와 행동).
 */

/** 요약과 목록이 함께 읽는 실행 목록의 상한. 이 범위 밖은 미확인으로 남는다. */
export const RECENT_EXECUTION_LIMIT = 50;

export const recentExecutionsQueryKey = ["screening-executions", "recent", RECENT_EXECUTION_LIMIT] as const;

export function isScreeningTerminal(status: ScreeningStatus | undefined | null): boolean {
  return status === "성공" || status === "부분 성공" || status === "실패" || status === "중단됨";
}

/** 확인이 필요한 종결 상태. 성공은 여기 들어가지 않는다. */
export function needsAttention(status: ScreeningStatus): boolean {
  return status === "부분 성공" || status === "실패" || status === "중단됨";
}

/**
 * 최근 판정 실행 목록. 회차 하나가 아니라 화면 전체가 쓰는 범위이며 상한이
 * 있다. 진행 중인 실행이 범위 안에 있을 때만 자동 갱신한다.
 */
export function useRecentScreeningExecutions() {
  return useQuery({
    queryKey: recentExecutionsQueryKey,
    queryFn: ({ signal }) => api.listScreeningExecutions({ limit: RECENT_EXECUTION_LIMIT, offset: 0 }, { signal }),
    staleTime: 3_000,
    refetchInterval: (query) => {
      const data = query.state.data;
      if (!data) return false;
      return data.items.some((item) => !isScreeningTerminal(item.status)) ? 5_000 : false;
    },
  });
}

/** 회차별로 가장 최근(대기열 번호가 큰) 실행. 조회 범위 밖이면 undefined. */
export function latestExecutionByRun(items: ScreeningExecutionResponse[]): Map<string, ScreeningExecutionResponse> {
  const byRun = new Map<string, ScreeningExecutionResponse>();
  for (const item of items) {
    const current = byRun.get(item.source_run_id);
    if (!current || item.queue_no > current.queue_no) byRun.set(item.source_run_id, item);
  }
  return byRun;
}

export const stageLabels: Record<string, string> = {
  "기술 적합성": "기술 적합성",
  "실적 정합성": "실적 정합성",
  "공공 SI 적합성": "공공 SI 적합성",
  "사업성·자격 제약": "사업성·자격 제약",
  "전략 부합": "전략 부합",
  counterargument: "반론 검토",
  synthesis: "종합 판정",
  merge: "병합·검증",
  publish: "파생 회차 게시",
};

export const failureTypeLabels: Record<string, string> = {
  timeout: "모델 응답 시간 초과",
  truncated_output: "모델 출력 잘림",
  schema_violation: "결과 형식 위반",
  evidence_missing: "근거 위치 확인 실패",
  counterargument_repetition: "반론 반복",
};

/** 서버가 준 실패 유형 코드를 사람이 읽는 사유로 옮긴다. 코드는 그대로 남긴다. */
export function failureReason(failureType: string): string {
  return failureTypeLabels[failureType] ?? "확인이 필요한 실패";
}

/** 건수. `null`은 0이 아니라 미확인이다. */
export function countLabel(value: number | null | undefined): string {
  return value === null || value === undefined ? "미확인" : `${value.toLocaleString("ko-KR")}건`;
}

/**
 * 진행률. 분모가 없거나 0이면 백분율을 만들지 않는다. 임의 백분율이나 남은
 * 시간을 추정하지 않는다(IMPLEMENTATION-CONTRACT §상태와 행동).
 */
export function progressPercent(execution: ScreeningExecutionResponse | null | undefined): number | null {
  if (!execution) return null;
  const candidate = execution.candidate_count;
  const processed = execution.completed_count + execution.failure_count;
  if (typeof candidate !== "number" || candidate <= 0) return null;
  return Math.min(100, Math.max(0, Math.round((processed / candidate) * 100)));
}

/** 실행이 끝난 뒤에도 남는 미처리 건수. 셀 수 없으면 null이다. */
export function remainingCount(execution: ScreeningExecutionResponse | null | undefined): number | null {
  if (!execution) return null;
  const candidate = execution.candidate_count;
  if (typeof candidate !== "number") return null;
  return Math.max(0, candidate - execution.completed_count - execution.failure_count);
}

/** 서버 오류 본문을 화면에 옮기지 않는다(docs/security.md). */
export function safeMessage(fallback: string): string {
  return fallback;
}

/**
 * 검증 지표 표시 규칙(H3, 대시보드 `검증 상태` 패널의 이식). `계산 불가`는
 * 0이 아니고, 측정값이 없으면 `미확인`이지 0이 아니다.
 */
export function validationMetricStatusLabel(metric: ValidationMetric): string {
  if (metric.status === "pass") return "통과";
  if (metric.status === "fail") return "미달";
  if (metric.status === "measured") return "측정";
  return "계산 불가";
}

export function validationMetricValueLabel(metric: ValidationMetric): string {
  if (metric.status === "not_measurable") return "계산 불가";
  if (metric.percentage !== null) return `${Number(metric.percentage.toFixed(1))}%`;
  return metric.value === null ? "미확인" : metric.value.toLocaleString("ko-KR");
}

/** `근거 {분자}/{분모}건`. 계산 불가 사유가 있으면 사유를 그대로 보인다. */
export function validationMetricBasisLabel(metric: ValidationMetric): string {
  if (metric.reason) return metric.reason;
  const { numerator, denominator } = metric.basis;
  const numeratorLabel = typeof numerator === "number" ? numerator.toLocaleString("ko-KR") : "미확인";
  const denominatorLabel = typeof denominator === "number" ? denominator.toLocaleString("ko-KR") : "미확인";
  return `근거 ${numeratorLabel}/${denominatorLabel}건`;
}
