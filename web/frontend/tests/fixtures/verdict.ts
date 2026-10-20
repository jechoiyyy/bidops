/**
 * RL-03 `/opportunities/:id/verdict` 판정 탭용 고정 응답.
 *
 * 모양은 RL-03 spec "REST"·HP-04 spec "API 계약"의 `bidops.practitioner-verdict-view.v1`에서 옮겼다.
 * 값은 **fixture 작성자의 창작값**이며 실제 공고·회사·모델 출력이 아니다. 정책 id·모델명·hash·품질
 * 표식은 일부러 눈에 띄는 값(`FORBIDDEN_VALUES`)으로 두어 실무 화면 DOM에 새는지 검사할 수 있게 한다.
 * 기대값은 화면 코드를 가져오지 않고 값으로 직접 적는다.
 *
 * 요구사항 표(`completedView().result.matrix`, 서버 순서가 일부러 부족 → 확인 필요 → 충족이 아니다):
 *   R1 충족 · 필수 · mapped 5쪽
 *   R2 확인 필요 · 필수 · inherited 12쪽(추정)
 *   R3 부족 · 필수 · mapped 3~4쪽, 인용 3개(패널은 2개만)
 *   R4 확인 필요 · 필수 미표기(null) · unavailable(쪽 미확인)
 *   R5 부족 · 조건부 · partial 7쪽
 *   R6 충족 · 필수 미표기(null) · mapped 9쪽
 *   R7 확인 필요 · 조건부 · 회사 근거(역할 의견) 없음, 인용 없음
 */
import type {
  PractitionerVerdictView,
  VerdictEvidenceRef,
  VerdictMatrixRow,
  VerdictResult,
} from "../../src/lib/types";
import { RL_COMPANY_ID } from "./company-rl";

export const VERDICT_COMPANY_ID = RL_COMPANY_ID;
/** 7101 사업기회의 사전규격 공고 pk(활동 fixture의 `pre_spec_opened`와 같다). */
export const VERDICT_NOTICE_ID = 9102;
export const VERDICT_ATTEMPT_ID = "a1000000-0000-4000-8000-000000000001";
export const VERDICT_STRUCTURE_ID = "c0000000-0000-4000-8000-000000000001";

export const SOURCE_SHA = "5".repeat(64);
export const POLICY_ID = "f0000000-0000-4000-8000-0000000000aa";
export const POLICY_SHA = "9".repeat(64);
export const COMPANY_VERSION_ID = "e0000000-0000-4000-8000-0000000000bb";
export const COMPANY_SHA = "7".repeat(64);
export const ONTOLOGY_SHA = "3".repeat(64);
export const MODEL_NAME = "gpt-6-luna";

/** 실무 화면(실행 정보 대화상자 밖) DOM에 없어야 하는 값들. */
export const FORBIDDEN_VALUES = [
  POLICY_ID,
  POLICY_SHA,
  SOURCE_SHA,
  COMPANY_SHA,
  ONTOLOGY_SHA,
  COMPANY_VERSION_ID,
  MODEL_NAME,
  "unmeasured_reference",
  "mock_reference",
  "analysis-policy-luna-rl-v1",
];

export const LONG_REASON =
  "자격 요건 중 직접생산 확인 세부 품명은 회사 근거에서 확인되지 않았고, 상주 인력은 요구보다 적게 등록되어 있어 조건부로만 진행할 수 있습니다. "
  + "기술 항목은 대부분 충족되지만 운영 SLA 일부는 확인이 필요하며, 역할별 의견이 갈린 항목은 담당자가 원문을 직접 확인해야 합니다.";

function ref(quote: string, blockKey: string): VerdictEvidenceRef {
  return { source_sha256: SOURCE_SHA, block_key: blockKey, quote };
}

function row(
  index: number,
  fit: VerdictMatrixRow["fit_status"],
  extra: Partial<VerdictMatrixRow> = {},
): VerdictMatrixRow {
  return {
    unit_id: `card:${SOURCE_SHA}:${index}:REQ-${String(index).padStart(3, "0")}`,
    type: "자격",
    fit_status: fit,
    role_findings: [
      { role: "eligibility_economics", assessment: fit, reason: `R${index}에 대한 자격·경제성 의견`, evidence_refs: [] },
    ],
    evidence_refs: [ref(`원문 인용 R${index}`, `b${index}`)],
    page_range: { first: index + 1, last: index + 1 },
    mapping_status: "mapped",
    normalized_requirement: `정규화된 요구사항 R${index}`,
    mandatory: true,
    fact_labels: [],
    ...extra,
  };
}

/** 서버 순서가 어긋난(충족이 앞) 일곱 행. 화면은 부족 → 확인 필요 → 충족, 동률은 이 순서로 보인다. */
export function sampleMatrix(): VerdictMatrixRow[] {
  return [
    row(1, "met", {
      type: "기술",
      normalized_requirement: "클라우드 기반 통합 인증 체계를 제공해야 한다",
      role_findings: [{ role: "technical_fit", assessment: "met", reason: "동일 계열 인증 구축 실적이 확인됨", evidence_refs: [] }],
      evidence_refs: [ref("통합 인증 체계를 제공하여야 한다.", "b1")],
      page_range: { first: 5, last: 5 },
      fact_labels: ["인증 구축 실적"],
    }),
    row(2, "unknown", {
      type: "인력",
      normalized_requirement: "정보보호 전문 인력 3명 이상을 상주시켜야 한다",
      role_findings: [{ role: "eligibility_economics", assessment: "unknown", reason: "상주 가능 인원의 현재 가용 기준이 확인되지 않음", evidence_refs: [] }],
      evidence_refs: [ref("정보보호 전문 인력 3명 이상 상주", "b2"), ref("상주 인력은 계약 체결 즉시 투입", "b3")],
      page_range: { first: 12, last: 12 },
      mapping_status: "inherited",
      fact_labels: ["상주 인원", "상주 지역"],
    }),
    row(3, "gap", {
      type: "자격",
      normalized_requirement: "직접생산 확인증명서(소프트웨어)를 보유해야 한다",
      role_findings: [{ role: "eligibility_economics", assessment: "gap", reason: "직접생산 확인 품목에 해당 소프트웨어가 없음", evidence_refs: [] }],
      evidence_refs: [ref("직접생산 확인증명서 보유 업체", "b4"), ref("공고일 현재 유효한 증명서", "b5"), ref("세 번째 인용은 패널에 나오지 않는다", "b6")],
      page_range: { first: 3, last: 4 },
      fact_labels: ["직접생산 확인"],
    }),
    row(4, "unknown", {
      type: "운영",
      normalized_requirement: "장애 발생 시 30분 이내 대응 체계를 갖추어야 한다",
      mandatory: null,
      role_findings: [{ role: "operations_risk", assessment: "unknown", reason: "SLA 수용 여부는 사람의 확인이 필요함", evidence_refs: [] }],
      evidence_refs: [ref("장애 발생 시 30분 이내 대응", "b7")],
      page_range: null,
      mapping_status: "unavailable",
    }),
    row(5, "gap", {
      type: "계약",
      normalized_requirement: "성과물의 지식재산권은 발주기관에 귀속한다",
      mandatory: false,
      role_findings: [{ role: "operations_risk", assessment: "gap", reason: "귀속 조건을 수용한다는 근거가 없음", evidence_refs: [] }],
      evidence_refs: [ref("지식재산권은 발주기관에 귀속", "b8")],
      page_range: { first: 7, last: 7 },
      mapping_status: "partial",
    }),
    row(6, "met", {
      type: "실적",
      normalized_requirement: "최근 3년 내 유사 사업 수행 실적 1건 이상",
      mandatory: null,
      role_findings: [{ role: "eligibility_economics", assessment: "met", reason: "유사 사업 수행 실적 2건이 확인됨", evidence_refs: [] }],
      evidence_refs: [ref("유사 사업 수행 실적 1건 이상", "b9")],
      page_range: { first: 9, last: 9 },
      fact_labels: ["유사 사업 실적"],
    }),
    row(7, "unknown", {
      type: "보안",
      normalized_requirement: "개인정보 처리 시스템은 보안 인증을 받아야 한다",
      mandatory: false,
      role_findings: [],
      evidence_refs: [],
      page_range: { first: 14, last: 15 },
    }),
  ];
}

function completedResult(matrix: VerdictMatrixRow[]): VerdictResult {
  return {
    verdict: "조건부 진행",
    reason: LONG_REASON,
    blocking_condition_ids: [],
    checklist: [
      { key: "qualification_track_record", status: "gap", evidence_refs: [] },
      { key: "staffing_onsite", status: "unknown", evidence_refs: [] },
      { key: "amount_period", status: "met", evidence_refs: [] },
      { key: "technology", status: "met", evidence_refs: [] },
      { key: "operations_sla_security", status: "unknown", evidence_refs: [] },
    ],
    matrix,
    cautions: [],
    conflicts: [],
    next_actions: [
      { unit_id: matrix[2]?.unit_id ?? "", owner: "박팀장", action: "직접생산 확인증명서 품목을 발급기관에 확인한다", evidence_refs: [], origin: null },
      { unit_id: matrix[1]?.unit_id ?? "", owner: null, action: "상주 가능 인력의 현재 가용 기준을 정리한다", evidence_refs: [], origin: null },
    ],
  };
}

const BASE: Omit<PractitionerVerdictView, "availability" | "attempt_id" | "result"> = {
  schema_version: "bidops.practitioner-verdict-view.v1",
  company_id: VERDICT_COMPANY_ID,
  notice_id: VERDICT_NOTICE_ID,
  is_current: true,
  stale_reasons: [],
  quality_status: "unmeasured_reference",
  identity: { policy_id: POLICY_ID, policy_sha256: POLICY_SHA, model: MODEL_NAME, reasoning_effort: "high", cli_version: "0.162.1" },
  source_binding: {
    document_versions: [{ document_version_id: "d0000000-0000-4000-8000-0000000000cc", source_sha256: SOURCE_SHA, structure_id: VERDICT_STRUCTURE_ID }],
    company_version_id: COMPANY_VERSION_ID,
    company_sha256: COMPANY_SHA,
    ontology_sha256: ONTOLOGY_SHA,
  },
  partial_stage_ids: [],
  error_code: null,
  missing_sections: [],
  started_at: "2026-10-16T09:12:00+09:00",
  finished_at: "2026-10-16T09:51:00+09:00",
  partial_matrix: [],
  briefing_item_id: null,
  opportunity_id: 7101,
  rejected_units: [],
};

/** 결정 B51: 추출 검증에서 격리된 unit의 표 행(유형 null·확인 필요·역할 의견 없음·규칙 코드). */
export function rejectedRow(index: number, ruleCodes: string[]): VerdictMatrixRow {
  return row(index, "unknown", {
    type: null,
    role_findings: [],
    evidence_refs: [],
    normalized_requirement: null,
    mandatory: null,
    fact_labels: [],
    rejected_rule_codes: ruleCodes,
  });
}

/** 결정 B51: 격리된 unit 두 개(카드 하나·영역 segment 하나)가 있는 완료 판정. */
export function rejectedCompletedView(): PractitionerVerdictView {
  const matrix = [...sampleMatrix(), rejectedRow(8, ["constraint_quote_truncated"]),
    rejectedRow(9, ["evidence_quote_not_verbatim", "requirement_number_untraceable"])];
  return completedView({
    rejected_units: [
      { unit_id: matrix[7].unit_id, normalized_id: "REQ-8", rule_codes: ["constraint_quote_truncated"] },
      { unit_id: matrix[8].unit_id, normalized_id: null, rule_codes: ["evidence_quote_not_verbatim", "requirement_number_untraceable"] },
    ],
  }, matrix);
}

/**
 * 결정 C19: 정책 v10 완료 판정 — 역할 밖 요구사항을 가리킨 역할 주의 하나(카드에 없는 id)와
 * 종합에서 빠진 다음 행동 하나(근거가 그 요구사항 근거와 다름)·주의 하나(역할 결과에 없는 id).
 */
export function synthesisIsolatedCompletedView(): PractitionerVerdictView {
  const matrix = sampleMatrix();
  return completedView({
    role_isolations: [
      { role: "operations_risk", unit_id: "card:unknown", normalized_id: null, kind: "caution",
        rule_codes: ["role_caution_foreign_unit"] },
    ],
    synthesis_isolations: [
      { unit_id: matrix[0].unit_id, normalized_id: "REQ-1", kind: "next_action",
        rule_codes: ["synthesis_evidence_outside_unit"] },
      { unit_id: "card:unknown", normalized_id: null, kind: "caution", rule_codes: ["synthesis_unit_outside_roles"] },
    ],
  }, matrix);
}

/** 결정 B55: 정책 v9 완료 판정 — 모델 행 하나 뒤에 코드가 붙인 "사람 확인" 행(누락 영역 하나·격리 unit 하나). */
export function codeActionsCompletedView(): PractitionerVerdictView {
  const view = rejectedCompletedView();
  const result = view.result!;
  const rejected = view.rejected_units![0];
  return {
    ...view,
    missing_sections: ["contract"],
    result: {
      ...result,
      next_actions: [
        { ...result.next_actions[1], origin: "model" },
        { unit_id: "missing_section:contract", owner: null, evidence_refs: [], origin: "code",
          action: "원문에서 '계약조건' 영역을 찾지 못했습니다. 이 영역의 조건을 원문에서 사람이 확인하세요." },
        { unit_id: rejected.unit_id, owner: null, evidence_refs: [], origin: "code",
          action: "원문 근거 검증에 실패한 요구사항입니다. 원문에서 사람이 확인하세요(자동으로 고치지 않음)." },
      ],
    },
  };
}

/** 판정 없음. 권위 연결 사전규격이 없으면 서버처럼 `notice_id=null`이다(0으로 접지 않는다). */
export function noneView(opportunityId: number, noticeId: number | null = null): PractitionerVerdictView {
  return {
    ...BASE,
    notice_id: noticeId,
    availability: "none",
    attempt_id: null,
    is_current: false,
    quality_status: null,
    identity: null,
    source_binding: null,
    result: null,
    started_at: null,
    finished_at: null,
    opportunity_id: opportunityId,
  };
}

export function completedView(overrides: Partial<PractitionerVerdictView> = {}, matrix: VerdictMatrixRow[] = sampleMatrix()): PractitionerVerdictView {
  return { ...BASE, availability: "completed", attempt_id: VERDICT_ATTEMPT_ID, result: completedResult(matrix), ...overrides };
}

export function runningView(availability: "pending" | "running" = "running"): PractitionerVerdictView {
  const [first, second] = sampleMatrix().filter((entry) => entry.fit_status !== "met");
  return {
    ...BASE,
    availability,
    attempt_id: VERDICT_ATTEMPT_ID,
    result: null,
    finished_at: null,
    partial_matrix: availability === "running" ? [first, second] : [],
  };
}

export function failedView(
  availability: "failed" | "needs_human_review" = "needs_human_review",
  errorCode = "card_extract_invalid",
): PractitionerVerdictView {
  const [gap] = sampleMatrix().filter((entry) => entry.fit_status === "gap");
  return {
    ...BASE,
    availability,
    attempt_id: VERDICT_ATTEMPT_ID,
    result: null,
    error_code: errorCode,
    missing_sections: ["eligibility", "evaluation"],
    partial_matrix: [gap],
  };
}

export function legacyView(): PractitionerVerdictView {
  return { ...BASE, availability: "legacy", attempt_id: "a2000000-0000-4000-8000-000000000002", result: null, identity: null, source_binding: null, quality_status: null };
}

/** 60행(부족 20 · 확인 필요 20 · 충족 20). 50행 페이지·"n건 더 보기" 검사용. */
export function largeMatrix(): VerdictMatrixRow[] {
  const fits = ["gap", "unknown", "met"] as const;
  return Array.from({ length: 60 }, (_, index) => row(100 + index, fits[index % 3], {
    normalized_requirement: `대량 요구사항 ${String(index + 1).padStart(2, "0")}`,
    role_findings: [{ role: "technical_fit", assessment: fits[index % 3], reason: `대량 사유 ${index + 1}`, evidence_refs: [] }],
    evidence_refs: [ref(`대량 인용 ${index + 1}`, `bb${index}`)],
    page_range: { first: 1 + (index % 30), last: 1 + (index % 30) },
  }));
}

/** `GET /api/document-structures/{id}/pages/{n}` 응답의 쪽 블록. block_key b2·b3은 근거 인용이 가리키는 블록이다. */
export function pageBlocks(page: number) {
  return {
    structure_id: VERDICT_STRUCTURE_ID,
    page,
    metadata: { number: page, width: 595, height: 842, image_content_object_id: null },
    blocks: [
      { block_key: "b1", parent_block_key: null, type: "paragraph", page, bbox: null, text: `${page}쪽 첫 문단 원문`, confidence: null, attributes: {} },
      { block_key: "b2", parent_block_key: null, type: "paragraph", page, bbox: null, text: "정보보호 전문 인력 3명 이상 상주", confidence: null, attributes: {} },
      { block_key: "b9", parent_block_key: null, type: "paragraph", page, bbox: null, text: `${page}쪽 마지막 문단 원문`, confidence: null, attributes: {} },
    ],
  };
}
