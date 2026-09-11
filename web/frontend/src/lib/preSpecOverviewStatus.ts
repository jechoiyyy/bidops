import type { BadgeVariant } from "../components/common/Badge";
import type { OverviewRangeSource, PreSpecOverviewReviewStatus } from "./types";

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


/** 읽은 쪽 범위를 누가 정했는가. 셋은 서로 다른 뜻이며 fallback을 자동 선택
 * 성공처럼 보이게 하지 않는다. */
export const PRE_SPEC_OVERVIEW_RANGE_SOURCE_LABEL: Record<OverviewRangeSource, string> = {
  auto: "자동 선택",
  fallback: "앞부분 fallback",
  human: "담당자 지정",
};

/**
 * 서버가 정한 안전한 사유 코드의 사람 문구. 범위 선택 사유, 실행 실패 사유,
 * 비차단 경고, 주장 검증 실패 사유가 한 vocabulary다.
 *
 * **여기에 없는 코드는 문구를 지어내지 않고 코드 그대로 보여 준다**
 * (`web/frontend/AGENTS.md` "상태 표현"). 모르는 값을 아는 문구로 바꾸면 사람이
 * 원인을 잘못 읽는다.
 */
const OVERVIEW_REASON_LABEL: Record<string, string> = {
  // 범위 선택
  heading_scope: "문서 제목 구조에서 개요 범위를 골랐습니다.",
  range_fallback_head: "범위를 자동으로 고르지 못해 문서 앞부분을 읽었습니다.",
  scope_heading_missing: "개요에 해당하는 제목을 찾지 못했습니다.",
  scope_end_missing: "범위가 끝나는 제목을 찾지 못했습니다.",
  ambiguous_scope: "읽을 범위를 하나로 정하지 못했습니다.",
  ambiguous_scope_boundary: "범위 경계가 여러 곳으로 읽혀 하나로 정하지 못했습니다.",
  human_range_confirmed: "담당자가 범위를 지정했습니다.",
  // 실행 실패
  manifest_invalid: "읽을 쪽에서 본문 텍스트를 얻지 못했습니다.",
  draft_format_retry_exhausted: "모델 초안이 정해진 형식을 두 번 모두 어겼습니다.",
  semantic_response_invalid: "의미 검토 응답이 계약 형식을 어겼습니다.",
  timeout: "제한 시간 안에 끝나지 않았습니다.",
  input_capacity_exceeded: "입력이 정책 상한을 넘었습니다.",
  response_store_unavailable: "원응답 저장소를 쓸 수 없어 실행을 닫았습니다.",
  lease_expired: "실행 점유가 만료됐습니다.",
  runner_failed: "실행기가 실패했습니다.",
  overview_disabled: "개요 검토가 비활성이라 대기 중이던 실행을 닫았습니다.",
  // 결정적 검증 실패·경고
  required_fact_missing: "필수 항목의 주장이 없습니다.",
  duplicate_id: "주장 식별자가 중복됐습니다.",
  fact_empty: "주장 문장이 비어 있습니다.",
  evidence_missing: "인용이 없습니다.",
  page_out_of_range: "인용한 쪽이 읽은 범위 밖입니다.",
  quote_not_found: "인용문을 원문에서 찾지 못했습니다.",
  quote_ambiguous: "인용문이 원문에서 한 곳으로 정해지지 않습니다.",
  quote_empty: "인용문이 비어 있습니다.",
  analysis_reference_missing: "검토자 분석이 가리키는 주장이 없습니다.",
  analysis_premise_unverified: "검토자 분석의 전제가 검증되지 않았습니다.",
  quantity_mismatch: "수치가 원문과 다릅니다.",
  quantity_metadata_mismatch: "수치의 단위·VAT·기산점이 원문과 다릅니다.",
  quantity_relation_ambiguous: "수치의 역할을 원문에서 하나로 정할 수 없습니다.",
  quantity_unit_missing: "수치에 단위가 없습니다.",
  requirement_id_mismatch: "요구사항 식별자가 원문과 다릅니다.",
  date_mismatch: "날짜가 원문과 다릅니다.",
  latin_term_mismatch: "영문 표기가 원문과 다릅니다.",
  role_mismatch: "역할·주체가 원문과 다릅니다.",
  negation_mismatch: "긍정·부정이 원문과 다릅니다.",
  condition_mismatch: "조건이 원문과 다릅니다.",
  business_nature_mismatch: "사업의 성격이 원문과 다릅니다.",
  obligation_strengthened: "원문보다 강한 의무로 바뀌었습니다.",
  unsupported_fact: "원문이 뒷받침하지 않는 사실입니다.",
  company_capability_unverified: "확인되지 않은 회사 역량을 단정했습니다.",
  company_comparison_scope_mismatch: "회사 자료 대조 범위를 벗어났습니다.",
  unknown_contradicted: "미확인 항목이 원문과 어긋납니다.",
  unknown_reason_mismatch: "미확인 사유가 원문과 맞지 않습니다.",
  prompt_injection: "문서 안의 지시문을 따르려 한 응답입니다.",
  insufficient_evidence: "판단에 필요한 근거가 부족합니다.",
  input_limit_exceeded: "입력이 정책 상한을 넘었습니다.",
  output_limit_exceeded: "응답이 정책 상한을 넘었습니다.",
  fact_structure_missing: "응답에 필요한 구조가 없습니다.",
  fact_schema_invalid: "응답이 계약 형식을 어겼습니다.",
  duplicate_json_key: "응답 JSON에 중복 key가 있습니다.",
};

/**
 * 사유 코드 하나를 사람 문구로 옮긴다. 모르는 코드는 **그대로** 돌려준다.
 *
 * `pdf_preparation_failed:<code>`처럼 하위 코드를 붙여 오는 실패는 앞부분만
 * 번역하고 하위 코드는 표식으로 남긴다 — 원인을 지우지 않는다.
 */
export function preSpecOverviewReasonLabel(code: string): string {
  const known = OVERVIEW_REASON_LABEL[code];
  if (known) return known;
  const [prefix, ...rest] = code.split(":");
  if (prefix === "pdf_preparation_failed" && rest.length > 0) {
    return `PDF 준비에 실패했습니다 · ${rest.join(":")}`;
  }
  return code;
}
