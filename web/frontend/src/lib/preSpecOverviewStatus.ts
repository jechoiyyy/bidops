import type { BadgeVariant } from "../components/common/Badge";
import type { PreSpecOverviewReviewStatus } from "./types";

// 사전규격 상세(PreSpecDetailPage)와 사전규격 목록(PreSpecsPage 그룹 헤더)이
// 개요 검토 상태 10값의 표시 문구·배지 색을 각자 다시 정의하지 않도록 이
// 모듈로 추출한다 (docs/design/PLAN.md 3단계, CLAUDE.md "같은 업무 규칙을
// 복제하지 않는다"). notice에 prespec_overview_review 행이 아직 없는
// 경우(개요 검토 미시작)는 이 10값 중 어느 것도 아니며 별도로 표시한다.

export const PRE_SPEC_OVERVIEW_STATUS_LABEL: Record<PreSpecOverviewReviewStatus, string> = {
  awaiting_document: "문서 대기",
  awaiting_structure: "구조화 대기",
  preparing: "입력 준비 중",
  awaiting_model: "모델 실행 대기",
  queued: "실행 대기",
  running: "실행 중",
  needs_human_review: "사람 검토 필요",
  completed: "완료",
  failed: "실패",
  cancelled: "취소",
};

/** notice에 개요 검토 행이 아직 없을 때(overview_review_status === null)
 * 목록·그룹 헤더가 쓰는 고정 라벨. */
export const PRE_SPEC_OVERVIEW_NOT_STARTED_LABEL = "개요 검토 미시작";

export function preSpecOverviewStatusVariant(status: PreSpecOverviewReviewStatus): BadgeVariant {
  if (status === "completed") return "evidence-confirmed";
  // 실패는 오류이고 사람 검토 필요는 경고다. 같은 색으로 칠하면 "확인해
  // 주세요"와 "이건 실패했습니다"가 구분되지 않는다.
  if (status === "failed") return "danger";
  if (status === "needs_human_review") return "alert";
  return "neutral";
}

