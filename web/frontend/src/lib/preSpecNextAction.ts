import { describeDeadline } from "./deadline";
import { preSpecAutoPreparationReasonLabel } from "./preSpecAutoPreparation";
import type { PreSpecListItem } from "./types";

/** 안내만 선택한다. 추적 선택이나 심층 검토 실행 버튼을 대신하지 않는다. */
export function nextActionOf(item: PreSpecListItem): string {
  if (item.overview_review_status === "needs_human_review") return "사람 확인";
  if (item.overview_review_status === "failed" || item.overview_review_status === "cancelled") {
    return "개요 실행 실패·취소 확인";
  }
  if (item.auto_preparation_status === "blocked") {
    const reason = preSpecAutoPreparationReasonLabel(item.auto_preparation_reason);
    const code = item.auto_preparation_reason;
    return `문서 차단 사유 확인${reason ? ` · ${reason}` : ""}${code && code !== reason ? ` (${code})` : ""}`;
  }
  if (item.origin === "신규" && (item.tracking_status === null || item.tracking_status === "미선택")) {
    return "추적 결정하기";
  }
  if (item.tracking_status === "보류" || item.tracking_status === "종료") return "사업 추적에서 상태 확인";
  if (item.auto_preparation_status === "deep_review_ready_for_click") return "심층 검토 시작 승인";
  if (item.auto_preparation_status === "deep_review_started") return "심층 검토 진행 확인";
  if (item.auto_preparation_status === "waiting_attachments"
    || item.auto_preparation_status === "bundle_draft"
    || item.auto_preparation_status === "overview_running") return "문서 준비·개요 진행 중";
  if (describeDeadline(item.deadline_at).urgency === "passed") {
    return "의견등록 마감 경과 · 본공고 여부는 상세에서 확인";
  }
  if (item.overview_review_status === "completed") return "개요 결과 확인";
  return "현재 상태 확인";
}
