import { ApiError } from "./api";
import type { EngineReviewReason } from "./engineReviewApi";

const REASON_COPY = {
  tracking_required: "계속 추적 중인 사전규격에서 진행할 수 있어요.",
  documents_pending: "첨부 원문을 준비하고 있어요",
  original_hwp_required: "HWP 또는 HWPX 원본을 준비해 주세요.",
  unsafe_document: "안전 검사를 통과한 원본을 확인해 주세요.",
  structure_unavailable: "원문 구조를 확인할 수 없어요. 문서 준비 상태를 확인해 주세요.",
  company_bundle_unavailable: "회사 자료 묶음을 읽을 수 없어요.",
  company_bundle_invalid: "회사 자료 묶음의 구성과 검증 상태를 확인해 주세요.",
  engine_disabled: "이 환경에서는 엔진 분석이 꺼져 있어요.",
  engine_live_disabled: "이 환경에서는 실제 전송을 사용할 수 없어요.",
  budget_exhausted: "남은 분석 호출 상한을 확인해 주세요.",
  input_changed: "자료가 바뀌었어요. 다시 확인해 주세요.",
  preview_expired: "자료가 바뀌었어요. 다시 확인해 주세요.",
  engine_unavailable: "엔진을 사용할 수 없어요. 잠시 후 다시 시도해 주세요.",
  notice_not_latest: "최신 사전규격에서 분석을 요청할 수 있어요.",
  review_excluded: "검토 제외된 사전규격이에요.",
  request_required: "열린 분석 요청이 없어요.",
  idempotency_conflict: "같은 요청 ID에 다른 내용이 기록돼 있어요.",
  input_too_large: "분석 입력이 허용된 크기를 넘었어요.",
  actor_name_required: "사이드바에 담당자 이름을 입력해 주세요.",
  actor_name_invalid: "사이드바의 담당자 이름을 확인해 주세요.",
  not_found: "해당 사전규격이나 요청을 찾을 수 없어요.",
} satisfies Record<EngineReviewReason, string> & Record<string, string>;

export function engineReviewReason(code: string | null, fallback = "확인이 필요해요") {
  if (code && Object.hasOwn(REASON_COPY, code)) {
    return { message: REASON_COPY[code as keyof typeof REASON_COPY], code: null };
  }
  return { message: code ? "확인이 필요해요" : fallback, code };
}

export function engineReviewErrorCode(error: unknown): string | null {
  if (!(error instanceof ApiError)) return null;
  const envelope = error.detail;
  const details = envelope && typeof envelope === "object" && "details" in envelope ? envelope.details : null;
  const reason = details && typeof details === "object" && "reason" in details ? details.reason : null;
  return typeof reason === "string" && /^[a-z][a-z0-9_]*$/.test(reason) ? reason : error.code;
}
