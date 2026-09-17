/**
 * 입찰 변경 비교의 표시 라벨과 집계.
 *
 * 최종 Go/No-Go 목록(`pages/GoNoGoPage.tsx`)과 결정 화면(`pages/BidDeltaDecisionPage.tsx`)이
 * 같은 계약을 읽고 같은 낱말을 쓴다. 두 화면이 각자 다른 낱말로 같은 상태를 부르면
 * 담당자는 목록과 상세 사이에서 상태가 바뀐 것처럼 읽는다.
 *
 * 여기에는 업무 규칙이 없다. 서버가 준 값을 사람이 읽는 문자로 옮기고, 항목을
 * 세는 일만 한다. 저장 가능 여부·현재성 판단은 서버와 화면의 기존 자리에 그대로 있다.
 */
import type {
  BidDeltaComparisonSummary,
  BidDeltaEvidenceView,
  BidDeltaItemView,
  BidDeltaCategory,
  BidFinalDecisionView,
  CalculationStatus,
  ChangeStatus,
  Currentness,
  FinalDecisionBasisKind,
  Materiality,
  ResultStatus,
} from "./types";

/** 최종 결정의 근거 종류(ADR-0058). 목록·결정 화면·이력이 같은 낱말을 쓴다. */
export const BASIS_LABELS: Record<FinalDecisionBasisKind, string> = {
  comparison: "비교 결과 기준",
  notice_conditions: "공고 조건 기준",
};

/** 공고 조건 차수 간·사전규격 대비 비교 상태. `unknown`은 변경 없음이 아니다. */
export const CHANGE_STATUS_LABELS: Record<ChangeStatus, string> = {
  changed: "변경",
  unchanged: "변경 없음",
  unknown: "미확인",
};

/**
 * 결정이 묶인 근거 한 줄. 비교 근거는 비교 버전·결과 해시를, 공고 조건 근거는
 * 기준 입찰공고 ID와 관측 해시를 적는다. 서버가 준 값을 옮길 뿐 채우지 않는다.
 */
export function decisionBasisDetail(decision: BidFinalDecisionView): string {
  if (decision.basis_kind === "notice_conditions") {
    return `기준 입찰공고 ID ${decision.basis_notice_id ?? "값 없음"} · 관측 해시 ${shortHash(decision.basis_observation_sha256)}`;
  }
  return `비교 버전 ${decision.comparison_version ?? "값 없음"} · 결과 해시 ${shortHash(decision.result_sha256)}`;
}

export const CATEGORY_LABELS: Record<BidDeltaCategory, string> = {
  budget_and_economics: "금액·경제성",
  contract_period_and_schedule: "계약기간·일정",
  eligibility: "참가자격",
  joint_supply_and_subcontracting: "공동수급·하도급",
  scope_and_requirements: "과업·요구사항",
  evaluation: "평가",
  submission: "제출",
};

export const CALCULATION_LABELS: Record<CalculationStatus, string> = {
  pending: "pending · 대기 중",
  running: "running · 계산 중",
  completed: "completed · 계산 완료",
  failed: "failed · 계산 실패",
};

export const RESULT_LABELS: Record<ResultStatus, string> = {
  changed: "changed · 변경 있음",
  unchanged: "unchanged · 변경 없음",
  unknown: "unknown · 판단 불가",
  failed: "failed · 분석 실패",
};

export const MATERIALITY_LABELS: Record<Materiality, string> = {
  material: "material · 중요 변경",
  non_material: "non_material · 비중요 변경",
  unknown: "unknown · 중요도 미확인",
};

export const CURRENTNESS_LABELS: Record<Currentness, string> = {
  current: "current · 현재 유효",
  stale: "stale · 재검토 필요(오래된 결정)",
  unknown: "unknown · 현재성 미확인",
};

export const LOCATOR_LABELS: Record<BidDeltaEvidenceView["locator_type"], string> = {
  page: "페이지",
  paragraph: "문단",
  table_cell: "표 셀",
  bbox: "문서 영역",
};

/** 목록에서 쓰는 짧은 계산 상태. 상세의 `CALCULATION_LABELS`와 같은 상태를 가리킨다. */
export const SHORT_CALCULATION_LABELS: Record<CalculationStatus, string> = {
  pending: "계산 대기",
  running: "계산 중",
  completed: "비교 완료",
  failed: "계산 실패",
};

export function formatMoment(value: string | null): string {
  if (!value) return "값 없음";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString("ko-KR");
}

export function formatDate(value: string | null): string {
  if (!value) return "값 없음";
  const parsed = new Date(`${value}T00:00:00`);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleDateString("ko-KR");
}

export function shortHash(value: string | null): string {
  return value ? value.slice(0, 12) : "값 없음";
}

export function locatorText(evidence: BidDeltaEvidenceView): string {
  const locator = evidence.locator;
  const page = typeof locator.page === "number" ? `페이지 ${locator.page}` : null;
  const detail = evidence.locator_type === "bbox" && Array.isArray(locator.bbox)
    ? `bbox [${locator.bbox.map((value) => String(value)).join(", ")}]`
    : evidence.locator_type === "table_cell"
      ? `표 ${String(locator.table_key ?? "값 없음")} · 행 ${String(locator.row ?? "값 없음")} · 열 ${String(locator.column ?? "값 없음")}`
      : evidence.locator_type === "paragraph"
        ? `문단 ${String(locator.paragraph_key ?? locator.block_key ?? "값 없음")}`
        : null;
  return [page, detail].filter(Boolean).join(" · ") || JSON.stringify(locator);
}

/**
 * 근거 위치 한 줄. `page` locator는 `locatorText`가 이미 `페이지 12`로 적으므로
 * 종류 이름을 앞에 또 붙이지 않는다(`페이지 페이지 12`).
 */
export function evidenceLocationLabel(evidence: BidDeltaEvidenceView): string {
  const text = locatorText(evidence);
  const kind = LOCATOR_LABELS[evidence.locator_type];
  return text.startsWith(kind) ? text : `${kind} ${text}`;
}

export interface DeltaCounts {
  /** `changed` + `material`. 사람이 결정 전에 반드시 읽어야 하는 변경. */
  material: number;
  /** `changed` + `non_material`. 중요도가 낮다고 판단된 변경(표기만이라는 뜻은 아니다). */
  nonMaterial: number;
  /** `unknown`·`failed`·중요도 미확인. 변경 없음도 요건 충족도 아니다. */
  unresolved: number;
  /** `unchanged`. 양쪽 근거로 확인한 범위에서 변경이 없었다는 실제 값. */
  unchanged: number;
}

/**
 * 범주별 결과를 세 갈래로 나눈다.
 *
 * `unknown`·`failed`를 `unchanged`나 0으로 접지 않는다. 실제 0건과 결과가 아직
 * 없는 상태는 세는 자리가 아니라 **부르는 자리**에서 구분한다 — 이 함수는 항목이
 * 있을 때만 부른다.
 */
export function countDeltaItems(items: BidDeltaItemView[]): DeltaCounts {
  const counts: DeltaCounts = { material: 0, nonMaterial: 0, unresolved: 0, unchanged: 0 };
  for (const item of items) {
    if (item.result_status === "changed") {
      if (item.materiality === "material") counts.material += 1;
      else if (item.materiality === "non_material") counts.nonMaterial += 1;
      else counts.unresolved += 1;
      continue;
    }
    if (item.result_status === "unchanged") counts.unchanged += 1;
    else counts.unresolved += 1;
  }
  return counts;
}

/** 결정 전에 읽어야 하는 항목. 비중요 변경과 변경 없음은 뺀다(시안 `결정 전에 볼 항목`). */
export function decisionRelevantItems(items: BidDeltaItemView[]): BidDeltaItemView[] {
  return items.filter((item) => {
    if (item.result_status === "unchanged") return false;
    if (item.result_status === "changed" && item.materiality === "non_material") return false;
    return true;
  });
}

/**
 * 항목 하나의 갈래를 한 낱말로. 목록 오른쪽 끝에 붙는다.
 *
 * `non_material`은 **비중요 변경**이지 표기 변경이 아니다. 계약상 이 값은 문구만
 * 바뀐 경우뿐 아니라 중요도가 낮다고 판단된 실제 내용 변경도 포함한다(시안의 예시
 * 자료가 마침 표기 변경이었을 뿐이다). 원래의 `result_status`·`materiality`는
 * 항목 상세와 결과 상태 칸에 그대로 남는다.
 */
export function itemKindLabel(item: BidDeltaItemView): string {
  if (item.result_status === "changed") {
    if (item.materiality === "material") return "중요 변경";
    if (item.materiality === "non_material") return "비중요 변경";
    return "변경 · 중요도 미확인";
  }
  if (item.result_status === "unchanged") return "변경 없음";
  if (item.result_status === "unknown") return "확인 필요";
  return "분석 실패";
}

/**
 * 사람이 요청한 순서(`sequence`)가 가장 큰 비교.
 *
 * 제목이나 날짜로 "최신 문서 쌍"을 짐작하지 않는다. `sequence`는 서버가 매기는
 * 요청 순서이고, 이 값을 화면의 **기본 선택**으로만 쓴다. 어떤 비교를 볼지는
 * 사람이 다시 고를 수 있고, 새 비교의 문서 쌍은 결정 화면에서 사람이 직접 고른다.
 */
export function defaultComparison(comparisons: BidDeltaComparisonSummary[]): BidDeltaComparisonSummary | null {
  if (comparisons.length === 0) return null;
  return comparisons.reduce((latest, item) => (item.sequence > latest.sequence ? item : latest));
}
