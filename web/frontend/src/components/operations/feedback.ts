import { ApiError } from "../../lib/api";

export type OperationsWrite = "settings" | "always_on" | "schedule_execution";

/** Keep conflict handling tied to HTTP status, never backend detail wording. */
export function operationsWriteError(error: unknown, operation: OperationsWrite): string {
  if (error instanceof ApiError && error.status === 409) {
    if (operation === "settings") return "스케줄 설정이 다른 변경과 충돌했어요. 최신 설정을 다시 불러왔어요.";
    if (operation === "always_on") return "상시 운영 승인 조합이 바뀌었어요. 최신 게이트·정책 상태를 다시 확인해 주세요.";
    return "같은 기간의 정기 실행 상태가 바뀌었어요. 최신 실행 이력을 다시 불러왔어요.";
  }
  if (operation === "settings") return "스케줄 설정을 저장하지 못했어요. 입력과 현재 상태를 확인해 주세요.";
  if (operation === "always_on") return "상시 운영 상태를 변경하지 못했어요. 승인 조합과 담당자 입력을 확인해 주세요.";
  return "정기 실행을 예약하지 못했어요. 기간과 현재 실행 이력을 확인해 주세요.";
}
