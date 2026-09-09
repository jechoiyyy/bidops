import type { BadgeVariant } from "../components/common/Badge";
import type { PreSpecAutoPreparationStatus } from "./types";

// 자동 문서 준비 8값과 그 사유 코드의 표시 문구를 한곳에 둔다. 목록 행과 상세
// 단계 표시가 각자 다시 정의하면 같은 업무 규칙이 두 벌 생긴다(CLAUDE.md).
//
// 값은 전부 서버가 정한다. 화면은 첨부 건수나 묶음 상태로 이 값을 다시 계산하지
// 않고 받은 값을 그대로 보여 준다.

export const PRE_SPEC_AUTO_PREPARATION_STATUS_LABEL: Record<PreSpecAutoPreparationStatus, string> = {
  // "알 수 없음"이 아니라 "자동 준비 대상이 아님"이다.
  not_applicable: "자동 준비 대상 아님",
  waiting_attachments: "첨부 취득 대기",
  bundle_draft: "묶음 초안",
  bundle_ready: "묶음 확정",
  overview_running: "개요 검토 실행 중",
  deep_review_started: "심층 검토 자동 시작됨",
  deep_review_ready_for_click: "심층 검토 클릭 대기",
  blocked: "자동 준비 중단",
};

/** 서버가 주는 안전한 사유 코드. 계약에 없는 코드는 만들어 내지 않고 코드
 * 그대로 보여 준다 — 모르는 값을 아는 문구로 바꾸지 않는다. */
export const COMPANY_FIT_REASON_LABEL: Record<string, string> = {
  company_fit_disabled: "회사 핏 자동 판정이 비활성입니다.",
  company_fit_pending: "회사 핏 판정이 필요합니다.",
  company_fit_queued: "회사 핏 판정을 기다리고 있습니다.",
  company_fit_running: "회사 핏 판정 중입니다.",
  company_fit_stale: "개요·회사 프로필·정책이 바뀌어 새 판정이 필요합니다.",
  company_fit_mismatch: "회사 업무 범위와 불일치하여 자동 시작 조건을 충족하지 못했습니다.",
  company_fit_unknown: "회사 핏 판단에 필요한 정보가 부족하여 사람 확인이 필요합니다.",
  company_fit_failed: "회사 핏 실행에 실패하여 자동 시작할 수 없습니다.",
  company_fit_needs_human_review: "회사 핏 근거 검증에 실패하여 사람 확인이 필요합니다.",
  company_fit_validation_failed: "회사 핏 근거 검증에 실패하여 사람 확인이 필요합니다.",
  company_fit_reference_only: "참조 판정으로는 운영 자동 시작 조건을 충족할 수 없습니다.",
};

const REASON_LABEL: Record<string, string> = {
  ...COMPANY_FIT_REASON_LABEL,
  grade_not_priority: "우선 검토 등급이 아닙니다.",
  awaiting_fetch: "첨부 원문 취득이 끝나지 않았습니다.",
  no_ready_document: "구조화가 끝난 문서가 없습니다.",
  bundle_has_blocking_issues: "묶음에 차단 issue가 있습니다.",
  bundle_unchanged: "직전 묶음과 내용이 같아 새 준비를 만들지 않았습니다.",
  human_bundle_draft: "사람이 만든 초안 묶음이라 자동으로 확정하지 않습니다.",
  processing_failed: "처리가 실패했습니다.",
  not_sw_business: "SW사업대상이 아닙니다.",
  bundle_not_auto_ready: "자동 확정 조건을 채우지 못한 묶음입니다.",
  overview_not_completed: "개요 검토가 아직 끝나지 않았습니다.",
  overview_recommendation_closed: "개요 권고가 검토 종료입니다.",
  overview_bundle_mismatch: "개요가 본 묶음과 현재 묶음이 다릅니다.",
  service_unavailable: "필요한 버전이나 서비스를 확인할 수 없습니다.",
};

/** 사유가 없으면 `null`을 돌려준다. 사유 `null`은 정상이므로 호출부는 아무것도
 * 그리지 않는다 — 자리표시 문구로 바꾸지 않는다. */
export function preSpecAutoPreparationReasonLabel(reason: string | null | undefined): string | null {
  if (!reason) return null;
  return REASON_LABEL[reason] ?? reason;
}

export function preSpecAutoPreparationVariant(status: PreSpecAutoPreparationStatus): BadgeVariant {
  // `blocked`는 자동 준비가 **멈춘** 상태다. 확인이 필요한 경고가 아니라
  // 진행이 막힌 것이므로 오류 색을 쓴다.
  if (status === "blocked") return "danger";
  if (status === "deep_review_started" || status === "bundle_ready") return "evidence-confirmed";
  return "neutral";
}
