import type {
  PractitionerVerdictView,
  VerdictChecklistKey,
  VerdictEvidenceRef,
  VerdictFeedbackKind,
  VerdictFit,
  VerdictMatrixRow,
  VerdictName,
  VerdictNextAction,
  VerdictSectionKind,
  VerdictStaleReason,
} from "./types";

/*
 * 사업기회 판정 탭(RL-03 spec "화면", ui-spec §4.4)의 순수 도우미.
 *
 * 서버가 준 판정 view에 이름만 붙이고 거르고 센다. 판정·체크리스트 상태·대조 상태를 만들거나
 * 다시 계산하지 않는다. 이 파일의 어떤 값도 정책 id·모델명·hash·참조 실행 표식을 만들지 않는다.
 * `unit_id`는 원문 hash를 포함할 수 있어 화면에 그리지 않는다(메모리의 선택 식별자로만 쓴다).
 */

// ---------------------------------------------------------------------------
// 이름·색 의미

export const VERDICT_NAME_TONE: Record<VerdictName, "success" | "warning" | "error" | "muted"> = {
  "진행 가능": "success",
  "조건부 진행": "warning",
  "진행 어려움": "error",
  "판단 불가": "muted",
};

export type VerdictTone = "success" | "warning" | "error" | "muted";

export function verdictNameTone(name: string): VerdictTone {
  return (VERDICT_NAME_TONE as Record<string, VerdictTone>)[name] ?? "muted";
}

export const FIT_LABEL: Record<VerdictFit, string> = {
  met: "충족",
  gap: "부족",
  unknown: "확인 필요",
};

/** `unknown`은 부족이 아니다(HP §7). 색은 의미를 거들 뿐이고 글자가 항상 상태 이름이다. */
export const FIT_TONE: Record<VerdictFit, "success" | "error" | "warning"> = {
  met: "success",
  gap: "error",
  unknown: "warning",
};

export const CHECKLIST_LABEL: Record<VerdictChecklistKey, string> = {
  qualification_track_record: "자격·실적",
  staffing_onsite: "상주·인력",
  amount_period: "금액·기간",
  technology: "기술",
  operations_sla_security: "운영·SLA",
};

export const VERDICT_DISCLAIMER = "판정은 참고 의견입니다. 추적 여부와 참여 결정은 담당자가 정합니다.";

export const STALE_REASON_LABEL: Record<VerdictStaleReason, string> = {
  company_changed: "회사 근거가 그 뒤에 바뀌었습니다",
  ontology_changed: "분류 기준이 그 뒤에 바뀌었습니다",
  documents_changed: "공고 문서가 그 뒤에 바뀌었습니다",
  policy_changed: "분석 기준이 그 뒤에 바뀌었습니다",
  superseded: "더 새로운 판정이 있습니다",
};

/** 모르는 사유는 숨기지 않고 코드 그대로 둔다. */
export function staleReasonLabel(reason: string): string {
  return (STALE_REASON_LABEL as Record<string, string>)[reason] ?? reason;
}

export const SECTION_LABEL: Record<VerdictSectionKind, string> = {
  overview: "사업개요",
  schedule: "추진일정",
  budget: "사업예산",
  eligibility: "입찰참가자격",
  evaluation: "평가기준",
  contract: "계약조건",
};

export function sectionLabel(section: string): string {
  return (SECTION_LABEL as Record<string, string>)[section] ?? section;
}

export const FEEDBACK_KIND_LABEL: Record<VerdictFeedbackKind, string> = {
  wrong_verdict: "판정이 틀렸습니다",
  wrong_unit: "요구사항 항목이 잘못됐습니다",
  not_requirement: "요구사항이 아닙니다",
  source_mismatch: "원문과 다릅니다",
};

// ---------------------------------------------------------------------------
// 헤더 pill

export interface VerdictPill {
  label: string;
  tone: "success" | "warning" | "error" | "muted";
}

/**
 * 레코드 헤더의 판정 pill. 완료이면 판정 이름, 분석 중이면 "분석 중", 실패는 "사람 검토 필요"다.
 * 그 밖(없음·legacy·불러오기 전·오류)은 `null`이고 호출자가 기존 "분석 대기"를 둔다.
 */
export function headerVerdictPill(view: PractitionerVerdictView | null | undefined): VerdictPill | null {
  if (!view) return null;
  switch (view.availability) {
    case "completed":
      return view.result ? { label: view.result.verdict, tone: verdictNameTone(view.result.verdict) } : null;
    case "pending":
    case "running":
      return { label: "분석 중", tone: "muted" };
    case "failed":
    case "needs_human_review":
      return { label: "사람 검토 필요", tone: "warning" };
    default:
      return null;
  }
}

/** 최종 판정 결과가 있을 때만 "판정 보기"를 연다. */
export function hasVerdictResult(view: PractitionerVerdictView | null | undefined): boolean {
  return Boolean(view && view.availability === "completed" && view.result);
}

/** 이 상태에서는 새 판정 요청이 의미 없다(진행 중인 실행이 있다). */
export function isVerdictActive(view: PractitionerVerdictView | null | undefined): boolean {
  return view?.availability === "pending" || view?.availability === "running";
}

// ---------------------------------------------------------------------------
// 요구사항 표

export type FitFilter = "default" | "all" | VerdictFit;

export const FIT_FILTER_OPTIONS: ReadonlyArray<{ value: FitFilter; label: string }> = [
  { value: "default", label: "부족·확인 필요만" },
  { value: "all", label: "전체" },
  { value: "gap", label: "부족" },
  { value: "unknown", label: "확인 필요" },
  { value: "met", label: "충족" },
];

const FIT_RANK: Record<VerdictFit, number> = { gap: 0, unknown: 1, met: 2 };

/**
 * 표의 행. 서버가 이미 부족 → 확인 필요 → 충족, 동률은 동결 순서로 준다. 같은 규칙으로 안정 정렬만
 * 다시 해서(서버 순서를 동률에서 보존) 순서가 어긋난 응답도 표가 같은 규칙을 지키게 한다.
 */
export function sortMatrix(rows: readonly VerdictMatrixRow[]): VerdictMatrixRow[] {
  return rows
    .map((row, index) => ({ row, index }))
    .sort((left, right) => FIT_RANK[left.row.fit_status] - FIT_RANK[right.row.fit_status] || left.index - right.index)
    .map(({ row }) => row);
}

export interface FitCounts {
  total: number;
  gap: number;
  unknown: number;
  met: number;
}

/** "부족 a · 확인 필요 b · 충족 c"와 분모 n(= unit 수). ui-spec이 허용한 집계다. */
export function countFit(rows: readonly VerdictMatrixRow[]): FitCounts {
  const counts: FitCounts = { total: rows.length, gap: 0, unknown: 0, met: 0 };
  for (const row of rows) counts[row.fit_status] += 1;
  return counts;
}

export function filterMatrix(rows: readonly VerdictMatrixRow[], fit: FitFilter, mandatoryOnly: boolean): VerdictMatrixRow[] {
  return rows.filter((row) => {
    if (mandatoryOnly && row.mandatory !== true) return false;
    if (fit === "all") return true;
    if (fit === "default") return row.fit_status !== "met";
    return row.fit_status === fit;
  });
}

export const MATRIX_PAGE_SIZE = 50;

/** 요구사항 문장. 서버가 정규화 문장을 주지 않으면 첫 원문 인용으로 대신하고, 둘 다 없으면 그 사실을 적는다. */
export function requirementText(row: VerdictMatrixRow): string {
  const normalized = row.normalized_requirement?.trim();
  if (normalized) return normalized;
  const quote = row.evidence_refs[0]?.quote.trim();
  return quote || "요구사항 문장 없음";
}

export function mandatoryLabel(row: VerdictMatrixRow): string {
  if (row.mandatory === true) return "필수";
  if (row.mandatory === false) return "조건부";
  return "미표기";
}

/** 첫 역할 의견의 이유 한 줄. 역할 의견이 없으면 `null`이다. */
export function companyEvidenceText(row: VerdictMatrixRow): string | null {
  const reason = row.role_findings[0]?.reason.trim();
  return reason ? reason : null;
}

export function pageRangeLabel(row: VerdictMatrixRow): string | null {
  const range = row.page_range;
  if (!range || row.mapping_status === "unavailable") return null;
  return range.first === range.last ? `${range.first}쪽` : `${range.first}~${range.last}쪽`;
}

/** 원문 칸 뒤에 붙는 보조 글자. 상속 쪽은 "(추정)", 일부 매핑은 "(일부 매핑)"이다. */
export function mappingSuffix(row: VerdictMatrixRow): string | null {
  if (!pageRangeLabel(row)) return null;
  if (row.mapping_status === "inherited") return "(추정)";
  if (row.mapping_status === "partial") return "(일부 매핑)";
  return null;
}

/** 원문 패널 제목. 쪽을 모르면 링크도 없고 제목에 "쪽 미확인"을 적는다. */
export function sourcePanelTitle(row: VerdictMatrixRow): string {
  const label = pageRangeLabel(row);
  return label ? `원문 · ${label}` : "원문 · 쪽 미확인";
}

/** 패널에 보이는 인용은 최대 2개다. */
export const SOURCE_QUOTE_LIMIT = 2;

export function panelQuotes(row: VerdictMatrixRow): VerdictEvidenceRef[] {
  return row.evidence_refs.slice(0, SOURCE_QUOTE_LIMIT);
}

/**
 * "쪽 전체 보기"가 읽을 문서 구조 id. 근거 인용의 문서 hash로 문서 버전을 찾고, 근거가 없으면 문서가
 * 하나뿐일 때만 그 문서로 본다. 서버가 `structure_id`를 주지 않았으면 `null`이고 화면은 추정하지 않는다.
 */
export function resolveStructureId(view: PractitionerVerdictView | null | undefined, row: VerdictMatrixRow): string | null {
  const documents = view?.source_binding?.document_versions ?? [];
  const sha = row.evidence_refs[0]?.source_sha256;
  const byHash = sha ? documents.find((document) => document.source_sha256 === sha) : undefined;
  const target = byHash ?? (documents.length === 1 ? documents[0] : undefined);
  return target?.structure_id ?? null;
}

/** 한 줄 담당 표시. owner가 없으면 "미지정"이다. */
export function ownerLabel(action: VerdictNextAction): string {
  const owner = action.owner?.trim();
  return owner ? owner : "미지정";
}
