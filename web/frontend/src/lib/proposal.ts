import type {
  PractitionerVerdictView,
  ProposalDraft,
  ProposalDraftStatus,
  ProposalSection,
  ProposalSectionKey,
  ProposalSectionStatus,
  ProposalSentence,
  ProposalSourceKind,
  ProposalStage,
  VerdictFit,
  VerdictMatrixRow,
} from "./types";

/*
 * 제안서 초안 탭(RL-04 spec "화면", ui-spec §4.5)의 순수 도우미.
 *
 * 서버 `ProposalView`에 이름을 붙이고 거르고 센다. 문장의 출처·종류·절 상태·단계 전이는 만들지
 * 않는다. 센 값은 spec이 허용한 집계(절 탭의 확인 건수, 채워야 할 것의 힌트별 건수, 분량)뿐이고
 * 확인할 문장·비어 있는 자리 숫자는 서버 `counters`를 그대로 쓴다. 정책 id·모델명·hash·토큰 수는
 * 이 파일의 어떤 값도 만들지 않는다. `unit_id`는 원문 hash를 포함할 수 있어 화면에 그리지 않는다.
 */

// ---------------------------------------------------------------------------
// 절

/** 절 6개의 고정 순서와 화면 이름(spec "절과 목차 대응"). */
export const SECTION_KEYS: readonly ProposalSectionKey[] = [
  "overview",
  "track_record",
  "strategy",
  "requirements",
  "operations_sla",
  "organization",
];

export const SECTION_LABEL: Record<ProposalSectionKey, string> = {
  overview: "제안 개요",
  track_record: "사업수행 실적",
  strategy: "수행 전략",
  requirements: "요구사항 수행방안",
  operations_sla: "운영·SLA",
  organization: "수행조직",
};

export function sectionLabel(key: string): string {
  return (SECTION_LABEL as Record<string, string>)[key] ?? key;
}

export function findSection(draft: ProposalDraft, key: ProposalSectionKey): ProposalSection | null {
  return draft.sections.find((section) => section.section_key === key) ?? null;
}

export const SECTION_STATUS_LABEL: Record<ProposalSectionStatus, string> = {
  queued: "대기",
  running: "생성 중",
  completed: "검토 전",
  failed: "생성 실패",
  reviewed: "검토 완료",
};

/** 모르는 상태는 숨기지 않고 코드 그대로 둔다. */
export function sectionStatusLabel(status: string): string {
  return (SECTION_STATUS_LABEL as Record<string, string>)[status] ?? status;
}

export type PillTone = "success" | "warning" | "error" | "muted";

/** 검토 전·대기·생성 중은 중립이다. 실패만 error, 검토 완료만 success다. 글자가 항상 상태 이름이다. */
export const SECTION_STATUS_TONE: Record<ProposalSectionStatus, PillTone> = {
  queued: "muted",
  running: "muted",
  completed: "muted",
  failed: "error",
  reviewed: "success",
};

export function sectionStatusTone(status: string): PillTone {
  return (SECTION_STATUS_TONE as Record<string, PillTone>)[status] ?? "muted";
}

export function isSectionActive(section: ProposalSection | null): boolean {
  return section?.status === "queued" || section?.status === "running";
}

/** 문장을 가진 절이다(생성이 끝나 본문이 있다). */
export function hasSectionBody(section: ProposalSection | null): section is ProposalSection {
  return section !== null && (section.status === "completed" || section.status === "reviewed");
}

// ---------------------------------------------------------------------------
// 초안 상태·단계

export const DRAFT_STATUS_LABEL: Record<ProposalDraftStatus, string> = {
  queued: "생성 대기",
  running: "생성 중",
  completed: "생성 완료",
  partial: "일부 절 실패",
  failed: "생성 실패",
  superseded: "이전 초안",
};

export function draftStatusLabel(status: string): string {
  return (DRAFT_STATUS_LABEL as Record<string, string>)[status] ?? status;
}

export function isDraftActive(draft: ProposalDraft | null | undefined): boolean {
  return draft?.status === "queued" || draft?.status === "running";
}

/** 헤더 pill이 아니라 좌측 stepper가 읽는 4단계. 서버 `stage`를 그대로 순서에만 쓴다. */
export const STAGE_STEPS: ReadonlyArray<{ stage: ProposalStage; label: string }> = [
  { stage: "toc", label: "목차" },
  { stage: "draft", label: "초안" },
  { stage: "reviewed", label: "검토 완료" },
  { stage: "ready", label: "제출 준비" },
];

export type StepState = "done" | "current" | "upcoming";

/**
 * stepper 한 칸의 상태. 현재 단계 앞은 완료, 현재는 링, 뒤는 대기다. 마지막 단계(`ready`)에 이르면 되돌리기가
 * 없으므로 그 칸도 완료로 닫는다.
 */
export function stepState(stage: string, index: number): StepState {
  const current = STAGE_STEPS.findIndex((step) => step.stage === stage);
  if (current < 0) return "upcoming";
  if (index < current) return "done";
  if (index === current) return current === STAGE_STEPS.length - 1 ? "done" : "current";
  return "upcoming";
}

export const STEP_STATE_LABEL: Record<StepState, string> = {
  done: "완료",
  current: "현재 단계",
  upcoming: "대기",
};

// ---------------------------------------------------------------------------
// 문장

export function allSentences(section: ProposalSection): ProposalSentence[] {
  return section.paragraphs.flatMap((paragraph) => paragraph.sentences);
}

/** 절 안에서 사람이 채우거나 확인할 문장(빈 자리 + 제안 수치). 절 탭 pill이 읽는다. */
export function sectionConfirmCount(section: ProposalSection | null): number {
  if (!section) return 0;
  return allSentences(section).filter((sentence) => sentence.kind !== "statement").length;
}

/** 분량 = 전체 문장 수(생성이 끝난 절만). */
export function totalSentenceCount(draft: ProposalDraft): number {
  return draft.sections.reduce((sum, section) => sum + (hasSectionBody(section) ? allSentences(section).length : 0), 0);
}

export interface NeedEntry {
  hint: string;
  count: number;
}

/** "채워야 할 것": 빈 자리(placeholder)를 힌트별로 센다. 힌트가 같은 자리는 한 줄로 묶는다. */
export function placeholderNeeds(draft: ProposalDraft): NeedEntry[] {
  const counts = new Map<string, number>();
  for (const section of draft.sections) {
    if (!hasSectionBody(section)) continue;
    for (const sentence of allSentences(section)) {
      if (sentence.kind !== "placeholder") continue;
      const hint = sentence.placeholder_hint?.trim() || "힌트 없음";
      counts.set(hint, (counts.get(hint) ?? 0) + 1);
    }
  }
  return [...counts.entries()].map(([hint, count]) => ({ hint, count }));
}

export const SOURCE_KIND_LABEL: Record<ProposalSourceKind, string> = {
  requirement_unit: "공고 요구사항 원문",
  company_fact: "회사 근거",
  notice_meta: "공고 정보",
};

export function sourceKindLabel(kind: string): string {
  return (SOURCE_KIND_LABEL as Record<string, string>)[kind] ?? kind;
}

const META_KEY_LABEL: Record<string, string> = {
  title: "공고명",
  agency: "발주기관",
  deadline_at: "마감 일시",
  method: "계약 방법",
  estimated_price: "추정가격",
};

/**
 * 출처의 보조 표기. 공고 정보는 한글 이름, 회사 근거는 `fact_key` 그대로다. 요구사항 원문은 unit id가 원문 hash를
 * 포함할 수 있어 `null`(그 자리에 인용문만 보인다).
 */
export function sourceRefLabel(kind: string, ref: string): string | null {
  if (kind === "requirement_unit") return null;
  if (kind === "notice_meta") return META_KEY_LABEL[ref] ?? ref;
  return ref;
}

/** 문장 수정 글자 수 상한(spec: 1..400자). */
export const SENTENCE_MAX = 400;

// ---------------------------------------------------------------------------
// 요구사항 연결

export interface LinkedRequirement {
  /** 표의 행 key. unit id를 그리지 않으므로 순번이다. */
  key: string;
  unitId: string;
  paragraphId: string;
  /** 판정 표에서 찾은 요구사항 문장. 찾지 못하면 `null`이다. */
  text: string | null;
  fitStatus: VerdictFit;
  factLabels: string[];
  /** 절 안의 문단 순번(1부터). 문단을 찾지 못하면 `null`이다. */
  paragraphNumber: number | null;
}

/**
 * "이 절이 답하는 요구사항" 표의 행. 대조 상태·연결은 서버가 준 `requirement_links` 그대로이고, 요구사항 문장과
 * 근거 라벨은 같은 레코드의 판정 표(`unit_id`로 매칭)에서 읽는다. 판정 표에 없으면 문장을 지어내지 않는다.
 */
export function linkedRequirements(
  section: ProposalSection,
  verdictView: PractitionerVerdictView | null,
  requirementText: (row: VerdictMatrixRow) => string,
): LinkedRequirement[] {
  const matrix = verdictView?.result?.matrix ?? [];
  const byUnit = new Map(matrix.map((row) => [row.unit_id, row] as const));
  const paragraphIndex = new Map(section.paragraphs.map((paragraph, index) => [paragraph.paragraph_id, index + 1] as const));
  return section.requirement_links.map((link, index) => {
    const row = byUnit.get(link.unit_id) ?? null;
    return {
      key: `q${index}`,
      unitId: link.unit_id,
      paragraphId: link.paragraph_id,
      text: row ? requirementText(row) : null,
      fitStatus: link.fit_status,
      factLabels: (row?.fact_labels ?? []).filter((label) => label.trim().length > 0),
      paragraphNumber: paragraphIndex.get(link.paragraph_id) ?? null,
    };
  });
}

export const REQUIREMENT_PAGE_SIZE = 50;

// ---------------------------------------------------------------------------
// 헤더 액션을 막는 이유

/** PDF 내보내기를 막는 이유. 열 수 있으면 `null`이다. */
export function exportBlockedReason(draft: ProposalDraft | null | undefined, busy: boolean): string | null {
  if (!draft) return "아직 만든 초안이 없습니다";
  if (draft.status === "queued" || draft.status === "running") return "초안 생성이 끝난 뒤 내보낼 수 있습니다";
  if (draft.status === "failed") return "내보낼 수 있는 초안이 없습니다";
  if (draft.status === "superseded") return "이전 초안은 내보내지 않습니다. 최신 초안에서 내보내십시오";
  return busy ? "처리 중입니다" : null;
}

/** 새 초안을 만들 수 없는 이유. 열 수 있으면 `null`이다. `draft`가 없으면 본문의 `초안 만들기`가 연다. */
export function regenerateDraftBlockedReason(
  draft: ProposalDraft | null | undefined,
  verdictCompleted: boolean,
  busy: boolean,
): string | null {
  if (!draft) return "아직 만든 초안이 없습니다. 본문의 초안 만들기를 쓰십시오";
  if (isDraftActive(draft)) return "초안을 만드는 중입니다";
  if (!verdictCompleted) return "아직 완료된 판정이 없습니다";
  return busy ? "처리 중입니다" : null;
}

/** 제출 준비 표시를 막는 이유. `reviewed`에서만 열린다. */
export function readyBlockedReason(draft: ProposalDraft | null | undefined, busy: boolean): string | null {
  if (!draft) return "아직 만든 초안이 없습니다";
  if (draft.status === "superseded") return "이전 초안은 바꿀 수 없습니다";
  if (draft.stage === "ready") return "이미 제출 준비로 표시했습니다";
  if (draft.stage !== "reviewed") return "모든 절을 검토 완료로 표시한 뒤 열립니다";
  return busy ? "처리 중입니다" : null;
}
