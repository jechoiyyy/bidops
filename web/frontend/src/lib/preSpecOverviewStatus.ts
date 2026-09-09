import type { BadgeVariant } from "../components/common/Badge";
import type {
  PreSpecOverviewAttemptStatus,
  PreSpecOverviewReviewStatus,
  PreSpecOverviewValidationStatus,
} from "./types";

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

/** 검증된 결과가 없을 때 그 상태가 무엇을 기다리는지. 상세(PreSpecDetailPage)와
 * 목록의 개요 탭(PreSpecsPage)이 같은 문장을 각자 다시 적지 않도록 여기에 둔다
 * (CLAUDE.md "같은 업무 규칙을 복제하지 않는다"). 결과가 없다는 사실을 다른
 * 상태의 설명으로 바꾸지 않는다. */
export const PRE_SPEC_OVERVIEW_WAITING_DESCRIPTION: Record<PreSpecOverviewReviewStatus, string> = {
  awaiting_document: "검토할 문서가 아직 준비되지 않아 개요 입력을 만들지 못했습니다.",
  awaiting_structure: "문서 구조화가 끝나고 개요 입력 범위가 확정되기를 기다리고 있습니다.",
  preparing: "서버가 개요 검토용 입력을 고정하고 있습니다.",
  awaiting_model: "승인된 모델 연결이 없어 아직 실행하지 않았습니다. 승인된 사설 모델 연결이 준비되기 전에는 모델을 부르지 않습니다.",
  queued: "승인된 모델 실행이 큐에서 차례를 기다리고 있습니다.",
  running: "승인된 모델 실행이 진행 중이며 검증된 결과를 기다리고 있습니다.",
  needs_human_review: "입력 범위 또는 실행 결과를 사람이 확인해야 하므로 검증된 권고로 확정할 수 없습니다.",
  completed: "처리 상태는 완료지만 검증된 결과 payload가 없어 권고를 표시할 수 없습니다.",
  failed: "모델 실행 또는 결과 검증이 실패했습니다. 실패 결과를 권고로 보정하지 않습니다.",
  cancelled: "실행이 취소되어 검증된 권고 결과가 없습니다.",
};

/** 개요 모델 실행(attempt) 상태의 표시 문구. 상세와 목록의 처리 이력이 같은
 * 문구를 쓴다. */
export const PRE_SPEC_OVERVIEW_ATTEMPT_STATUS_LABEL: Record<PreSpecOverviewAttemptStatus, string> = {
  queued: "대기",
  running: "실행 중",
  completed: "완료",
  failed: "실패",
  cancelled: "취소",
};

/** 결정적 검증 상태 셋의 표시 문구와 경고. `passed`가 아닌 결과를 판정으로 읽지
 * 않게 하는 경고 문장이 계약이며, 두 화면이 같은 문구를 쓴다. */
export const PRE_SPEC_OVERVIEW_VALIDATION: Record<
  PreSpecOverviewValidationStatus,
  { label: string; variant: BadgeVariant; warning: string | null }
> = {
  passed: { label: "검증 통과 · passed", variant: "evidence-confirmed", warning: null },
  failed: { label: "검증 실패 · failed", variant: "danger", warning: "검증에 실패한 결과입니다. 이 내용을 판정으로 읽지 마세요." },
  pending: { label: "검증 대기 · pending", variant: "neutral", warning: "아직 결정적 검증을 통과하지 않은 결과입니다. 이 내용을 판정으로 읽지 마세요." },
};

/**
 * 개요 v2 응답이 **요청한 notice의 정본인지**만 확인한다.
 *
 * envelope과 nested review의 `notice_id`가 모두 요청 값과 같아야 한다. 어긋나면
 * 다른 공고의 결과를 이 화면에 그리지 않는다 — 교차 정본은 조용히 표시하지 않고
 * 화면이 그 사실을 밝힌다. 목록과 상세가 같은 판정을 쓴다.
 */
export function hasCanonicalOverviewNoticeId(
  response: unknown,
  noticeId: number,
): response is { notice_id: number; reviews: Array<{ notice_id: number }> } {
  if (typeof response !== "object" || response === null) return false;
  if (!("notice_id" in response) || !("reviews" in response)) return false;
  const candidate = response as { notice_id?: unknown; reviews?: unknown };
  return candidate.notice_id === noticeId
    && Array.isArray(candidate.reviews)
    && candidate.reviews.every((review) => (
      typeof review === "object"
      && review !== null
      && "notice_id" in review
      && review.notice_id === noticeId
    ));
}
