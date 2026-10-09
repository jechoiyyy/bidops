import { BidDeltaApiError } from "../components/bid-delta/api";
import { DeepReviewApiError } from "../components/deep-review/api";
import { ApiError, OrderPlanBulkTrackingResultUnconfirmedError } from "./api";

/**
 * 화면 하나의 오류 문구 정책.
 *
 * 지금까지 화면마다 규칙이 셋이었다 — 서버 메시지를 통째로 버리는 고정 문구,
 * 서버 raw message + 코드, `TypeError` 원문을 이어 붙인 문장. 어느 것도 원인과
 * 다음 행동을 함께 말하지 않았고, 마지막 둘은 서버가 만든 문자열을 그대로
 * 화면에 실었다.
 *
 * `docs/security.md`: API 오류 본문은 UI 전송 계약이 아니다. 서버 message,
 * 원문, 내부 경로, provider 진단은 화면에 내지 않는다. 남기는 것은 **안전한
 * 오류 코드**뿐이며, 그것도 `[a-z][a-z0-9_]*` 모양일 때만 코드로 인정한다.
 * 그렇지 않으면 서버가 message를 code 자리에 실어 보내는 것과 구분할 수 없다.
 *
 * 이 함수는 재판정이 아니다. 서버가 준 status와 안전한 code를 사람이 읽을 수
 * 있는 제목·설명·다음 행동으로 옮길 뿐이며, 없는 상태를 만들어 내지 않는다.
 */

/** 오류 뒤에 사람이 할 수 있는 행동. `null`은 지금 할 수 있는 행동이 없다는 뜻이다. */
export type ApiErrorAction = "retry" | "reload" | "contact" | null;

export interface ApiErrorDescription {
  /** 무엇이 일어났는지. 화면 맥락이 아니라 원인을 말한다. */
  title: string;
  /** 다음에 무엇을 할지. 항상 한 문장 이상으로 행동을 말한다. */
  detail: string;
  action: ApiErrorAction;
  /** 서버가 준 안전한 오류 코드. 사람 문구가 없어도 이 표식은 보존한다. */
  code: string | null;
}

export const API_ERROR_ACTION_LABEL: Record<Exclude<ApiErrorAction, null>, string> = {
  retry: "다시 시도",
  reload: "최신 상태 다시 불러오기",
  contact: "담당자에게 문의",
};

/** 서버 message가 code 자리에 실려 화면으로 새는 것을 막는 모양 검사. */
const SAFE_CODE_PATTERN = /^[a-z][a-z0-9_]{0,63}$/;

export type OrderPlanBulkTrackingErrorKind = "server" | "validation" | "result_unconfirmed";

export interface OrderPlanBulkTrackingError {
  status: number;
  kind: OrderPlanBulkTrackingErrorKind;
  code: string | null;
  request_id: string | null;
}

type CodeDescription = Omit<ApiErrorDescription, "code">;

/**
 * 화면이 아는 안전한 코드의 한국어 문구.
 *
 * 정본은 backend의 `app/deep_review/agents/common/errors.py`가 고정한 안전한
 * 오류 코드 집합이다. 여기에 없는 코드는 문구를 지어내지 않고 status 규칙으로
 * 떨어지며, 코드 자체는 표식으로 남는다.
 */
const KNOWN_CODE_DESCRIPTION: Record<string, CodeDescription> = {
  review_not_ready: {
    title: "보고서가 아직 준비되지 않았습니다.",
    detail: "분석이 끝나야 보고서를 조회할 수 있습니다. 잠시 뒤 다시 조회하십시오.",
    action: "retry",
  },
  active_attempt_exists: {
    title: "이미 실행 중인 분석 회차가 있습니다.",
    detail: "지금 실행이 끝난 뒤에 새 회차를 시작할 수 있습니다. 최신 상태를 다시 불러와 확인하십시오.",
    action: "reload",
  },
  version_conflict: {
    title: "대상이 그사이 바뀌었습니다.",
    detail: "다른 사람이 먼저 바꿨을 수 있습니다. 최신 상태를 다시 불러온 뒤 입력을 확인하십시오.",
    action: "reload",
  },
  idempotency_conflict: {
    title: "같은 요청 식별자가 다른 요청에 이미 쓰였습니다.",
    detail: "같은 저장을 두 번 보내지 않도록 화면을 다시 불러온 뒤 처음부터 입력하십시오.",
    action: "reload",
  },
  company_identity_conflict: {
    title: "같은 회사 식별자에 다른 정보가 등록되어 있습니다.",
    detail: "등록된 회사 이름과 가상회사 표식을 확인한 뒤 다시 시도하십시오.",
    action: null,
  },
  bundle_not_ready: {
    title: "확정된 문서 묶음이 필요합니다.",
    detail: "문서 준비에서 문서 묶음을 확정한 뒤 다시 시도하십시오.",
    action: null,
  },
  bundle_has_blocking_issues: {
    title: "문서 묶음에 해결되지 않은 차단 항목이 있습니다.",
    detail: "문서 준비에서 차단 항목을 먼저 해결해야 합니다. 화면이 차단을 건너뛰지 않습니다.",
    action: null,
  },
  unsafe_document: {
    title: "문서가 안전 검사를 통과하지 못했습니다.",
    detail: "검사에 걸린 문서는 사용할 수 없습니다. 문서 준비에서 상태를 확인하십시오.",
    action: null,
  },
  structure_unavailable: {
    title: "문서 구조를 확인할 수 없습니다.",
    detail: "구조화가 끝나지 않았거나 실패했습니다. 잠시 뒤 다시 시도하십시오.",
    action: "retry",
  },
  evidence_out_of_scope: {
    title: "심층 검토 범위 밖의 근거입니다.",
    detail: "이 보고서 범위 안의 근거만 쓸 수 있습니다. 입력한 근거 식별자를 확인하십시오.",
    action: null,
  },
  factual_change_evidence_required: {
    title: "사실을 바꾸려면 범위 안의 근거가 필요합니다.",
    detail: "바뀐 사실이 가리키는 근거 식별자를 입력한 뒤 다시 저장하십시오.",
    action: null,
  },
  final_opinion_reason_required: {
    title: "의견 사유가 필요합니다.",
    detail: "사유를 입력한 뒤 다시 저장하십시오.",
    action: null,
  },
  validation_failed: {
    title: "결정적 검증을 통과하지 못했습니다.",
    detail: "실패한 검증은 자동으로 보정되지 않습니다. 근거를 사람이 확인해야 합니다.",
    action: null,
  },
  effective_grade_ineligible: {
    title: "현재 공고는 이 작업의 대상이 아닙니다.",
    detail: "서버가 등급 조건으로 막았습니다. 등급과 대상 조건을 확인하십시오.",
    action: null,
  },
  run_active: {
    title: "이미 진행 중인 개요 검토가 있습니다.",
    detail: "지금 실행이 끝난 뒤에 새 범위로 다시 검토할 수 있습니다. 최신 상태를 다시 불러와 확인하십시오.",
    action: "reload",
  },
  document_not_current_safe: {
    title: "개요를 읽을 문서가 현재 버전이 아니거나 안전 검사를 통과하지 않았습니다.",
    detail: "문서 준비에서 묶음의 제안요청서 상태를 확인한 뒤 다시 시도하십시오.",
    action: null,
  },
  range_invalid: {
    title: "쪽 범위가 올바르지 않습니다.",
    detail: "시작 쪽은 1 이상이고 끝 쪽보다 클 수 없으며 문서의 쪽 수와 정책 상한을 넘을 수 없습니다. 범위를 고쳐 다시 보내십시오.",
    action: null,
  },
  actor_name_required: {
    title: "담당자 이름이 필요합니다.",
    detail: "담당자 이름을 입력한 뒤 다시 저장하십시오. 이름은 감사 표식이며 인증이 아닙니다.",
    action: null,
  },
  actor_name_invalid: {
    title: "담당자 이름이 올바르지 않습니다.",
    detail: "이름을 다시 입력한 뒤 저장하십시오.",
    action: null,
  },
  bid_delta_comparison_stale: {
    title: "새 비교 입력이 생겨 이 결정은 최신이 아닙니다.",
    detail: "최신 상태를 다시 불러온 뒤 어떤 비교를 결정할지 확인하십시오.",
    action: "reload",
  },
  bid_delta_version_conflict: {
    title: "비교 버전이 그사이 바뀌었습니다.",
    detail: "다른 사람이 먼저 바꿨을 수 있습니다. 최신 상태를 다시 불러온 뒤 확인하십시오.",
    action: "reload",
  },
  bid_delta_result_digest_conflict: {
    title: "비교 결과가 그사이 바뀌었습니다.",
    detail: "저장하려던 결과와 지금 결과가 다릅니다. 최신 상태를 다시 불러온 뒤 확인하십시오.",
    action: "reload",
  },
  final_decision_supersession_conflict: {
    title: "직전 최종 결정이 그사이 바뀌었습니다.",
    detail: "다른 사람이 먼저 결정했을 수 있습니다. 최신 상태를 다시 불러온 뒤 확인하십시오.",
    action: "reload",
  },
  bid_delta_currentness_unavailable: {
    title: "비교의 최신 여부를 확인할 수 없습니다.",
    detail: "최신 여부를 모르는 채로 결정을 저장하지 않았습니다. 최신 상태를 다시 불러오십시오.",
    action: "reload",
  },
  bid_delta_comparison_not_completed: {
    title: "계산이 끝난 비교만 최종 결정할 수 있습니다.",
    detail: "계산이 완료될 때까지 기다린 뒤 다시 저장하십시오.",
    action: null,
  },
  bid_delta_comparison_not_retryable: {
    title: "계산에 실패한 비교만 다시 실행할 수 있습니다.",
    detail: "현재 상태를 확인한 뒤 필요한 작업을 고르십시오.",
    action: null,
  },
  bid_delta_input_not_ready: {
    title: "비교 입력이 아직 준비되지 않았습니다.",
    detail: "문서 준비에서 문서 묶음을 확정한 뒤 다시 시도하십시오.",
    action: null,
  },
  bid_delta_input_not_authoritative: {
    title: "확정된 연결이 아닌 문서로는 비교할 수 없습니다.",
    detail: "사업 추적에서 연결이 확정된 뒤에 비교를 시작할 수 있습니다.",
    action: null,
  },
  bid_delta_category_policy_invalid: {
    title: "지원하지 않는 범주 정책입니다.",
    detail: "화면을 다시 불러온 뒤에도 같으면 담당자에게 알리십시오.",
    action: "reload",
  },
  bid_delta_service_unavailable: {
    title: "입찰 변경 비교 기능을 일시적으로 사용할 수 없습니다.",
    detail: "잠시 뒤 다시 시도하고, 계속되면 담당자에게 알리십시오.",
    action: "retry",
  },
  bid_delta_projection_unavailable: {
    title: "입찰 변경 비교 정보를 조회할 수 없습니다.",
    detail: "잠시 뒤 다시 시도하고, 계속되면 담당자에게 알리십시오.",
    action: "retry",
  },
  not_found: {
    title: "대상을 찾을 수 없습니다.",
    detail: "요청한 대상이 없거나 이미 지워졌습니다. 목록에서 다시 여십시오.",
    action: null,
  },
  service_unavailable: {
    title: "서비스를 일시적으로 사용할 수 없습니다.",
    detail: "잠시 뒤 다시 시도하고, 계속되면 담당자에게 알리십시오.",
    action: "retry",
  },
  processing_failed: {
    title: "작업을 완료하지 못했습니다.",
    detail: "실패는 자동으로 보정되지 않습니다. 잠시 뒤 다시 시도하고, 계속되면 담당자에게 알리십시오.",
    action: "retry",
  },
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** 세 오류형 모두 `status`를 갖는다. 그 밖의 오류는 status가 없다(`null`). */
function readStatus(error: unknown): number | null {
  if (error instanceof ApiError || error instanceof DeepReviewApiError || error instanceof BidDeltaApiError) {
    return error.status;
  }
  if (isRecord(error) && typeof error.status === "number" && Number.isInteger(error.status)) {
    return error.status;
  }
  return null;
}

function safeCode(value: unknown): string | null {
  return typeof value === "string" && SAFE_CODE_PATTERN.test(value) ? value : null;
}

/**
 * Distinguish the stable server envelope from FastAPI's request-validation
 * shape.  Bulk callers use this instead of branching on server messages.
 */
export function parseOrderPlanBulkTrackingError(error: unknown): OrderPlanBulkTrackingError | null {
  if (error instanceof OrderPlanBulkTrackingResultUnconfirmedError) {
    return {
      status: 0,
      kind: "result_unconfirmed",
      code: "result_unconfirmed",
      request_id: null,
    };
  }
  if (!(error instanceof ApiError)) return null;
  const envelope = isRecord(error.detail) && "code" in error.detail ? error.detail : null;
  return {
    status: error.status,
    kind: error.status === 422 && envelope === null ? "validation" : "server",
    code: envelope === null
      ? error.status === 422 ? "invalid_request" : null
      : safeCode(envelope.code),
    request_id: error.requestId,
  };
}

const BULK_RESULT_UNCONFIRMED_DESCRIPTION: ApiErrorDescription = {
  title: "일괄 추적 결과를 확인할 수 없습니다.",
  detail: "같은 요청 식별자와 입력을 그대로 사용해 저장된 요청 결과를 확인하십시오. 새 요청을 만들지 않습니다.",
  action: "retry",
  code: "result_unconfirmed",
};

/**
 * Bulk mutations have a stricter recovery rule than ordinary mutations:
 * response loss or parsing failure retries the same request, and an
 * idempotency conflict never asks the caller to mint a new request key.
 *
 * `unconfirmedTitle` lets a caller with more than one bulk operation (ADR-0063:
 * 시작·종료) say which one lost its response — the generic title below is the
 * shared default when the caller has only one meaning of "일괄 추적".
 */
export function describeOrderPlanBulkTrackingError(
  error: unknown,
  fallback = "일괄 추적 작업을 완료하지 못했습니다.",
  unconfirmedTitle: string = BULK_RESULT_UNCONFIRMED_DESCRIPTION.title,
): ApiErrorDescription {
  const parsed = parseOrderPlanBulkTrackingError(error);
  if (!parsed) return describeApiError(error, fallback);
  if (parsed.kind === "result_unconfirmed") return { ...BULK_RESULT_UNCONFIRMED_DESCRIPTION, title: unconfirmedTitle };
  if (parsed.code === "idempotency_conflict") {
    return {
      title: "같은 요청 식별자가 다른 요청에 이미 쓰였습니다.",
      detail: "요청 식별자와 입력을 바꾸지 말고 저장된 요청 결과를 확인하십시오.",
      action: "reload",
      code: parsed.code,
    };
  }
  if (parsed.kind === "validation") {
    return {
      title: "일괄 추적 요청 형식이 올바르지 않습니다.",
      detail: "선택한 발주계획과 요청 입력을 확인한 뒤 다시 시도하십시오.",
      action: null,
      code: parsed.code,
    };
  }
  return describeApiError(error, fallback);
}

/**
 * 안전한 오류 코드만 꺼낸다. `ApiError`는 typed code 자리가 없어 detail 객체의
 * `code`를 읽되, 모양 검사를 통과한 값만 코드로 인정한다.
 */
function readCode(error: unknown): string | null {
  if (error instanceof DeepReviewApiError || error instanceof BidDeltaApiError) {
    return safeCode(error.code);
  }
  if (error instanceof ApiError) {
    return isRecord(error.detail) ? safeCode(error.detail.code) : null;
  }
  if (isRecord(error) && "code" in error) return safeCode(error.code);
  return null;
}

/**
 * 오류를 제목·설명·다음 행동으로 옮긴다. `fallback`은 status도 코드도 없는
 * 오류에서만 제목으로 쓰인다 — 화면 맥락 문장을 여기에 넣는다.
 */
export function describeApiError(error: unknown, fallback: string): ApiErrorDescription {
  const status = readStatus(error);
  const code = readCode(error);

  if (error instanceof OrderPlanBulkTrackingResultUnconfirmedError) {
    return BULK_RESULT_UNCONFIRMED_DESCRIPTION;
  }

  if (status === 0) {
    return {
      title: "서버에 연결할 수 없습니다.",
      detail: "네트워크와 서버 상태를 확인한 뒤 다시 시도하십시오.",
      action: "retry",
      code: null,
    };
  }

  // 안전한 코드가 status보다 구체적이다. 서버가 403으로 막으면서 이유를 코드로
  // 알려 주면(예: `effective_grade_ineligible`) 그 문구를 쓰고, 코드가 없을 때만
  // status 규칙으로 떨어진다.
  if (code !== null) {
    const known = KNOWN_CODE_DESCRIPTION[code];
    if (known) return { ...known, code };
  }

  if (status === 401 || status === 403) {
    return {
      title: "이 작업을 수행할 권한이 없습니다.",
      detail: "서버가 요청을 거부했습니다. 사내망 접근 경계와 대상 조건을 담당자에게 확인하십시오.",
      action: "contact",
      code,
    };
  }

  if (status === 404) {
    return { ...KNOWN_CODE_DESCRIPTION.not_found, code };
  }

  if (status === 409) {
    return {
      title: "다른 변경과 충돌했습니다.",
      detail: "다른 사람이 먼저 바꿨을 수 있습니다. 최신 상태를 다시 불러온 뒤 확인하십시오.",
      action: "reload",
      code,
    };
  }

  if (status !== null && status >= 500) {
    return {
      title: "서버 오류가 발생했습니다.",
      detail: "서버가 요청을 처리하지 못했습니다. 잠시 뒤 다시 시도하고, 계속되면 담당자에게 알리십시오.",
      action: "retry",
      code,
    };
  }

  if (status !== null && status >= 400) {
    return {
      title: "요청을 처리할 수 없습니다.",
      detail: "입력한 값을 확인한 뒤 다시 시도하십시오.",
      action: null,
      code,
    };
  }

  return {
    title: fallback,
    detail: "원인을 확인할 수 없습니다. 다시 시도하고, 계속되면 담당자에게 알리십시오.",
    action: "retry",
    code,
  };
}

/**
 * 오류 표시에 붙일 행동 버튼 하나. `contact`와 `null`은 버튼을 만들지 않는다 —
 * 화면이 대신 문의할 수 없고, 없는 복구 경로를 버튼으로 지어내지 않는다.
 */
export function apiErrorRecoveryAction(
  description: ApiErrorDescription,
  onRecover: (() => void) | undefined,
  label?: string,
): { label: string; onClick: () => void } | undefined {
  if (!onRecover) return undefined;
  if (description.action !== "retry" && description.action !== "reload") return undefined;
  return { label: label ?? API_ERROR_ACTION_LABEL[description.action], onClick: onRecover };
}
