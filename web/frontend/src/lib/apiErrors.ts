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
  company_profile_not_ready: {
    title: "회사 프로필이 아직 준비되지 않았습니다.",
    detail: "회사 지식 버전을 활성화한 뒤 다시 여십시오.",
    action: null,
  },
  // RL-00 `GET /api/company`(deep_review `routers/company_knowledge.py` `_ERRORS`).
  company_not_registered: {
    title: "등록된 회사가 없습니다.",
    detail: "회사 파일을 등록하고 활성화한 뒤 다시 여십시오.",
    action: null,
  },
  // RL-01 브리핑(lifecycle `routers/briefings.py` 로컬 오류 map).
  briefing_not_found: {
    title: "브리핑이 아직 없습니다.",
    detail: "해당 날짜의 브리핑이 만들어지지 않았습니다. 평일 브리핑이 만들어진 뒤에 다시 여십시오.",
    action: null,
  },
  briefing_item_not_found: {
    title: "브리핑 항목을 찾을 수 없습니다.",
    detail: "항목이 없거나 다른 날짜의 브리핑에 속합니다. 최신 상태를 다시 불러온 뒤 확인하십시오.",
    action: "reload",
  },
  reaction_not_allowed: {
    title: "이 항목에는 반응을 남길 수 없습니다.",
    detail: "추적 중인 사업의 변화는 확인용 항목이며 반응 대상이 아닙니다.",
    action: null,
  },
  // RL-02 사업기회 레코드(lifecycle `routers/opportunities.py` 로컬 오류 map).
  note_not_action: {
    title: "다음 행동만 완료로 표시할 수 있습니다.",
    detail: "노트는 완료 대상이 아닙니다. 최신 상태를 다시 불러온 뒤 확인하십시오.",
    action: "reload",
  },
  opportunity_not_found: {
    title: "사업기회를 찾을 수 없습니다.",
    detail: "없거나 이미 지워진 사업기회입니다. 사업기회 목록에서 다시 여십시오.",
    action: null,
  },
  opportunity_merged: {
    title: "다른 사업기회로 병합된 사업기회입니다.",
    detail: "병합된 사업기회에는 노트를 남길 수 없습니다. 병합된 쪽 레코드를 여십시오.",
    action: "reload",
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
 * 가상회사 데모 회사 경로(`docs/work/demo-contract.md` §2·§9)의 안전한 오류 코드 문구.
 *
 * 정본은 backend 회사 router의 허용 목록이다: lifecycle `routers/companies.py`의
 * `_TRACKING_ERRORS`, deep_review `routers/company_knowledge.py`의 `_ERRORS`,
 * `services/company_projection.py`의 `READ_ERROR_STATUS`(company_reads),
 * `services/company_deep_review.py`의 `ERROR_STATUS`(company_analysis).
 * 허용 목록 중 공용 표의 문구가 회사 경로에서도 맞는 코드(`company_profile_not_ready`·
 * `bundle_not_ready`·`active_attempt_exists`·`review_not_ready`·`evidence_out_of_scope`·
 * `unsafe_document`·`actor_name_*`·`processing_failed`)는 공용 문구를 그대로 쓰고,
 * 회사 경로에서 뜻이 다르거나(`not_found`·`effective_grade_ineligible`·
 * `version_conflict`·`idempotency_conflict`) 공용 표에 없는 코드만 여기서 적는다.
 *
 * 기존 단일회사 화면의 문구를 바꾸지 않도록 공용 표에 섞지 않고 회사 화면만
 * `describeCompanyApiError`로 읽는다.
 */
const COMPANY_CODE_DESCRIPTION: Record<string, CodeDescription> = {
  not_found: {
    title: "이 회사에서 대상을 찾을 수 없습니다.",
    detail: "없는 대상이거나 다른 회사 소속입니다. 다른 회사의 결과로 대신 보여 주지 않습니다. 회사 목록에서 다시 여십시오.",
    action: null,
  },
  effective_grade_ineligible: {
    title: "SW사업대상 사전규격이 아닙니다.",
    detail: "회사 경로의 심층 분석은 SW사업대상=Y 공고만 받습니다. C-1 등급은 이 조건에 쓰지 않습니다.",
    action: null,
  },
  invalid_request: {
    title: "요청 형식이 올바르지 않습니다.",
    detail: "입력한 값을 확인한 뒤 다시 시도하십시오.",
    action: null,
  },
  tracking_status_invalid: {
    title: "지원하지 않는 추적 상태입니다.",
    detail: "계속 추적·보류·종료 중 하나를 고른 뒤 다시 저장하십시오.",
    action: null,
  },
  tracking_reason_required: {
    title: "추적 상태를 고른 이유가 필요합니다.",
    detail: "사유를 입력한 뒤 다시 저장하십시오.",
    action: null,
  },
  version_conflict: {
    title: "이 회사의 대상이 그사이 바뀌었습니다.",
    detail: "입력은 지우지 않았습니다. 최신 상태를 다시 불러온 뒤 입력을 확인하고 다시 저장하십시오. 자동으로 덮어쓰지 않습니다.",
    action: "reload",
  },
  idempotency_conflict: {
    title: "같은 요청 식별자가 다른 요청에 이미 쓰였습니다.",
    detail: "재전송이 앞선 요청과 충돌했습니다. 최신 상태를 다시 불러와 저장 여부를 확인하십시오.",
    action: "reload",
  },
  company_input_invalid: {
    title: "회사 분석 입력을 만들 수 없습니다.",
    detail: "회사·문서·그래프 버전이 서로 맞지 않습니다. 자동으로 보정하지 않으므로 회사 지식과 문서 준비 상태를 확인하십시오.",
    action: null,
  },
  overview_not_completed: {
    title: "개요 검토가 아직 완료되지 않았습니다.",
    detail: "개요 검토가 완료된 뒤에 회사별 심층 분석을 요청할 수 있습니다.",
    action: null,
  },
  review_exists: {
    title: "같은 입력의 심층 검토가 이미 있습니다.",
    detail: "새 검토를 만들지 않습니다. 기존 검토에서 새 분석 회차를 요청하십시오.",
    action: null,
  },
  preview_required: {
    title: "전송 미리보기 확인이 필요합니다.",
    detail: "전송 내용 미리보기를 다시 열어 확인한 뒤 승인하십시오.",
    action: null,
  },
  preview_changed: {
    title: "미리보기 뒤에 전송 입력이 바뀌었습니다.",
    detail: "이전 승인은 쓰지 않습니다. 전송 내용 미리보기를 다시 확인한 뒤 승인하십시오.",
    action: null,
  },
  preview_used: {
    title: "이미 승인에 쓰인 미리보기입니다.",
    detail: "같은 미리보기로 다시 요청하지 않습니다. 새 미리보기를 만들어 확인하십시오.",
    action: null,
  },
  reference_mode_required: {
    title: "참조 실행 모드가 꺼져 있습니다.",
    detail: "새 심층 분석 요청은 참조 실행 모드에서만 받습니다. 과거 결과 조회는 계속 할 수 있습니다.",
    action: null,
  },
  luna_disabled: {
    title: "Luna 심층 검토가 비활성입니다.",
    detail: "심층 분석 요청을 보낼 수 없습니다. 운영 설정은 담당자에게 확인하십시오.",
    action: "contact",
  },
  analysis_policy_unavailable: {
    title: "분석 정책을 사용할 수 없습니다.",
    detail: "데모 정책이 설정·등록되지 않았습니다. 다른 정책으로 대신 실행하지 않습니다. 담당자에게 확인하십시오.",
    action: "contact",
  },
  model_binding_invalid: {
    title: "분석 모델 설정이 유효하지 않습니다.",
    detail: "설정이 맞지 않아 호출 전에 막았습니다. 다른 모델로 대신 보내지 않습니다. 담당자에게 확인하십시오.",
    action: "contact",
  },
};

/** 회사 경로 화면의 오류 문구. 회사 표에 없는 코드는 공용 규칙(`describeApiError`)으로 떨어진다. */
export function describeCompanyApiError(error: unknown, fallback: string): ApiErrorDescription {
  const status = readStatus(error);
  const code = readCode(error);
  if (status !== 0 && code !== null) {
    const known = COMPANY_CODE_DESCRIPTION[code];
    if (known) return { ...known, code };
  }
  return describeApiError(error, fallback);
}

/**
 * RL-03 참여 판정(`GET|POST /api/opportunities/{id}/verdict*`, `POST …/verdict-feedback`)의 안전한 코드 문구.
 *
 * 정본은 RL-03 spec의 오류 code 목록이다. 요청 실패(`policy_not_approved`·`daily_cap_reached`·
 * `active_attempt_exists`·`bundle_not_ready`·`effective_grade_ineligible`·`opportunity_not_found`)와 실패한
 * 실행의 `error_code`(`card_*`·`input_budget_exceeded`)를 함께 적는다. 수동 요청·제보가 지나는 기존
 * 서비스 gate의 코드(`not_found`·`company_input_invalid`·`reference_mode_required`·`luna_disabled`·
 * `analysis_policy_unavailable`·`model_binding_invalid`·`idempotency_conflict`, backend
 * `company_deep_review.ERROR_STATUS`·`verdict_trigger.VerdictRequestError`·`verdict_view`)도 판정 문맥의
 * 문구로 적는다(회사 데모 화면 문구는 데모 정책을 말하므로 쓰지 않는다). spec이 쓰지 않기로 한
 * `analysis_in_progress`·`documents_not_ready`·`verdict_source_missing`·`overview_not_completed`는 적지
 * 않는다 — 서버가 내지 않는 코드의 문구를 화면이 미리 만들지 않는다. 표에 없는 코드는 공용 규칙으로
 * 떨어지고 코드 자체는 표식으로 남는다.
 */
const VERDICT_CODE_DESCRIPTION: Record<string, CodeDescription> = {
  not_found: {
    title: "판정할 사전규격을 찾을 수 없습니다.",
    detail: "이 사업기회에 연결된 사전규격이 없거나 실회사 판정 경로가 꺼져 있습니다. 다른 공고의 판정으로 대신 보여 주지 않습니다.",
    action: null,
  },
  company_input_invalid: {
    title: "판정 입력을 만들 수 없습니다.",
    detail: "회사 사실·문서·그래프 버전이 서로 맞지 않거나 보내면 안 되는 값이 섞였습니다. 자동으로 보정하지 않으므로 회사 정보와 문서 준비 상태를 확인하십시오.",
    action: null,
  },
  reference_mode_required: {
    title: "참조 실행 모드가 꺼져 있습니다.",
    detail: "새 판정 요청은 참조 실행 모드에서만 받습니다. 이미 있는 판정 조회는 계속 할 수 있습니다.",
    action: null,
  },
  luna_disabled: {
    title: "Luna 분석이 꺼져 있습니다.",
    detail: "판정 요청을 보낼 수 없습니다. 운영 설정은 담당자에게 확인하십시오.",
    action: "contact",
  },
  analysis_policy_unavailable: {
    title: "판정 분석 정책을 사용할 수 없습니다.",
    detail: "실회사 판정 정책이 설정·등록되지 않았습니다. 다른 정책으로 대신 실행하지 않습니다. 담당자에게 확인하십시오.",
    action: "contact",
  },
  model_binding_invalid: {
    title: "분석 모델 설정이 유효하지 않습니다.",
    detail: "설정이 맞지 않아 호출 전에 막았습니다. 다른 모델로 대신 보내지 않습니다. 담당자에게 확인하십시오.",
    action: "contact",
  },
  idempotency_conflict: {
    title: "같은 요청 식별자가 다른 요청에 이미 쓰였습니다.",
    detail: "재전송이 앞선 요청과 충돌했습니다. 최신 상태를 다시 불러와 요청·제보가 이미 저장됐는지 확인하십시오.",
    action: "reload",
  },
  policy_not_approved: {
    title: "분석 정책 전송 승인이 없습니다.",
    detail: "판정은 운영 담당자가 분석 정책을 승인한 뒤에만 시작합니다. 화면이 대신 승인하지 않습니다. 담당자에게 확인하십시오.",
    action: "contact",
  },
  daily_cap_reached: {
    title: "오늘 판정 한도에 도달했습니다.",
    detail: "하루에 시작할 수 있는 판정 수를 모두 썼습니다. 내일 다시 요청하거나 담당자에게 한도를 확인하십시오.",
    action: null,
  },
  active_attempt_exists: {
    title: "이미 분석 중인 판정이 있습니다.",
    detail: "지금 분석이 끝난 뒤에 다시 판정을 요청할 수 있습니다. 최신 상태를 다시 불러와 확인하십시오.",
    action: "reload",
  },
  bundle_not_ready: {
    title: "문서 준비가 끝나지 않았습니다.",
    detail: "공고 문서 묶음이 확정된 뒤에 판정을 요청할 수 있습니다. 문서 준비 상태를 확인하십시오.",
    action: null,
  },
  effective_grade_ineligible: {
    title: "SW사업 공고가 아니라 판정 대상이 아닙니다.",
    detail: "공고 메타의 SW사업 대상 표시가 Y인 사전규격만 판정합니다. 서버가 조건으로 막았습니다.",
    action: null,
  },
  opportunity_not_found: {
    title: "사업기회를 찾을 수 없습니다.",
    detail: "없거나 이미 지워진 사업기회입니다. 사업기회 목록에서 다시 여십시오.",
    action: null,
  },
  input_budget_exceeded: {
    title: "문서 한 단위가 분석 입력 한도를 넘었습니다.",
    detail: "원문을 자르지 않으므로 이 문서는 판정하지 못했습니다. 사람이 원문을 직접 확인해야 합니다.",
    action: null,
  },
  card_source_selection_incomplete: {
    title: "공고 원문에서 판정에 필요한 영역을 모두 찾지 못했습니다.",
    detail: "찾지 못한 영역이 원문에 없다는 뜻은 아닙니다. 아래 표는 검증을 통과한 부분만 보여 줍니다. 사람이 원문을 확인하십시오.",
    action: null,
  },
  card_extract_invalid: {
    title: "요구사항 추출 결과가 원문 검증을 통과하지 못했습니다.",
    detail: "검증에 실패한 결과는 자동으로 고치지 않습니다. 아래 표는 검증을 통과한 부분만 보여 줍니다.",
    action: null,
  },
  card_compare_invalid: {
    title: "회사 사실 대조 결과가 검증을 통과하지 못했습니다.",
    detail: "검증에 실패한 결과는 자동으로 고치지 않습니다. 아래 표는 검증을 통과한 부분만 보여 줍니다.",
    action: null,
  },
  card_role_invalid: {
    title: "역할별 검토 결과가 검증을 통과하지 못했습니다.",
    detail: "검증에 실패한 결과는 자동으로 고치지 않습니다. 아래 표는 검증을 통과한 부분만 보여 줍니다.",
    action: null,
  },
  card_synthesis_invalid: {
    title: "종합 판정이 검증을 통과하지 못했습니다.",
    detail: "검증에 실패한 결과는 자동으로 고치지 않습니다. 아래 표는 검증을 통과한 부분만 보여 줍니다.",
    action: null,
  },
  card_review_timeout: {
    title: "정해진 시간 안에 분석이 끝나지 않았습니다.",
    detail: "늦게 온 응답은 저장하지 않습니다. 아래 표는 검증을 통과한 부분만 보여 줍니다. 다시 판정으로 새 분석을 요청하십시오.",
    action: null,
  },
};

/** 판정 화면의 오류 문구. 판정 표에 없는 코드는 공용 규칙(`describeApiError`)으로 떨어진다. */
export function describeVerdictApiError(error: unknown, fallback: string): ApiErrorDescription {
  const status = readStatus(error);
  const code = readCode(error);
  if (status !== 0 && code !== null) {
    const known = VERDICT_CODE_DESCRIPTION[code];
    if (known) return { ...known, code };
  }
  return describeApiError(error, fallback);
}

/**
 * 실패한 판정 실행의 `error_code`를 사람 문구로 옮긴다. 화면에 문장이 있는 코드만 번역하고
 * **모르는 코드는 숨기지 않고 코드 그대로** 돌려준다(`detail`은 `null`).
 */
export function describeVerdictRunCode(code: string | null): { title: string; detail: string | null; code: string | null } | null {
  if (code === null) return null;
  const known = VERDICT_CODE_DESCRIPTION[code];
  if (known) return { title: known.title, detail: known.detail, code };
  return { title: "분석 중 안전 오류가 기록됐습니다.", detail: null, code };
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
