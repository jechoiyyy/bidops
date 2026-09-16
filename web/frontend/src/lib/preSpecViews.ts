import { GRADE_NONE_LABEL, GRADE_ORDER } from "./grade";
import { formatCompactPrice } from "./deadline";
import { formatNumber } from "./format";
import { originOf } from "./opportunity";
import {
  PRE_SPEC_OVERVIEW_NOT_STARTED_LABEL,
  PRE_SPEC_OVERVIEW_STATUS_LABEL,
} from "./preSpecOverviewStatus";
import type {
  PreSpecAutoPreparationStatus,
  PreSpecListItem,
  PreSpecDeadlineStatus,
  PreSpecNextAction,
  PreSpecOverviewView,
  PreSpecOverviewReviewStatus,
  PreSpecSort,
  PreSpecWorkspace,
} from "./types";

// 목록의 등급 필터 허용값은 API와 화면이 공유한다. 행을 다시 줄 세우거나
// 상태를 재계산하지 않고, 서버가 준 등급을 그대로 표시한다.
export const GRADE_FILTER_VALUES = [...GRADE_ORDER, GRADE_NONE_LABEL] as const;
type GradeFilter = (typeof GRADE_FILTER_VALUES)[number] | "";

export type WorkspaceKey = PreSpecWorkspace;
export type ViewKey = PreSpecOverviewView;

export interface WorkspaceDefinition {
  key: WorkspaceKey;
  label: string;
  description: string;
  defaultSort: PreSpecSort;
}

export interface ViewDefinition {
  key: ViewKey;
  label: string;
  /** `null`이면 전체(상태로 좁히지 않음). */
  statuses: readonly (PreSpecOverviewReviewStatus | null)[] | null;
  description: string;
}

export const WORKSPACES: readonly WorkspaceDefinition[] = [
  {
    key: "actionable",
    label: "검토할 항목",
    description: "사람 확인·심층 검토·추적 결정이 필요한 건",
    defaultSort: "deadline",
  },
  {
    key: "recent",
    label: "최근 수집",
    description: "최근 관측된 사전규격",
    defaultSort: "observed",
  },
  {
    key: "tracking",
    label: "추적 중",
    description: "계속 추적·보류 중인 사업",
    defaultSort: "published",
  },
  {
    key: "all",
    label: "전체 이력",
    description: "누적 사전규격 전체",
    defaultSort: "published",
  },
];

// 탐색 묶음이며 새로운 업무 상태가 아니다. 취소는 실패와 별도로 유지한다.
export const VIEWS: readonly ViewDefinition[] = [
  { key: "all", label: "전체 상태", statuses: null, description: "현재 필터에 맞는 사전규격 전체" },
  { key: "attention", label: "사람 확인 필요", statuses: ["needs_human_review"], description: "개요 입력 범위나 결과를 사람이 확인해야 하는 건" },
  {
    key: "pending",
    label: "진행·대기",
    statuses: ["awaiting_document", "awaiting_structure", "preparing", "awaiting_model", "queued", "running"],
    description: "개요 검토가 준비·실행을 기다리는 건",
  },
  { key: "not_started", label: "미시작", statuses: [null], description: "개요 검토 실행 기록이 없는 건" },
  { key: "completed", label: "개요 완료", statuses: ["completed"], description: "개요 검토가 완료된 건" },
  { key: "failed", label: "실패", statuses: ["failed"], description: "개요 검토가 실패한 건" },
  { key: "cancelled", label: "취소", statuses: ["cancelled"], description: "개요 검토 실행이 취소된 건" },
];

// 정렬은 서버 질의 인자이고 화면이 다시 줄 세우지 않는다.
export const SORT_OPTIONS: readonly { value: PreSpecSort; label: string }[] = [
  { value: "published", label: "게시 최신순" },
  { value: "deadline", label: "마감 임박순" },
  { value: "observed", label: "최근 관측순" },
];

export const DEADLINE_STATUS_OPTIONS: readonly { value: PreSpecDeadlineStatus; label: string }[] = [
  { value: "open", label: "마감 전" },
  { value: "passed", label: "마감 경과" },
  { value: "unknown", label: "마감 미확인" },
];

export const TRACKING_STATUS_OPTIONS = ["계속 추적", "보류", "종료", "미선택"] as const;

export const PRE_SPEC_NEXT_ACTION_LABEL: Record<PreSpecNextAction, string> = {
  confirm_overview: "개요 사람 확인",
  open_deep_review: "심층 검토 열기",
  decide_tracking: "추적 결정",
};

export function workspaceOf(key: WorkspaceKey): WorkspaceDefinition {
  return WORKSPACES.find((workspace) => workspace.key === key) ?? WORKSPACES[0];
}

export function validWorkspace(value: string | null): WorkspaceKey {
  return WORKSPACES.some((workspace) => workspace.key === value) ? value as WorkspaceKey : "actionable";
}

export function validOverviewView(value: string | null): ViewKey {
  return VIEWS.some((view) => view.key === value) ? value as ViewKey : "all";
}

export function validDeadlineStatus(value: string | null): PreSpecDeadlineStatus | "" {
  return DEADLINE_STATUS_OPTIONS.some((option) => option.value === value)
    ? value as PreSpecDeadlineStatus
    : "";
}

export function validTrackingStatus(value: string | null): typeof TRACKING_STATUS_OPTIONS[number] | "" {
  return TRACKING_STATUS_OPTIONS.includes(value as typeof TRACKING_STATUS_OPTIONS[number])
    ? value as typeof TRACKING_STATUS_OPTIONS[number]
    : "";
}

export function validObservedDate(value: string | null): string | "" {
  return value && /^\d{4}-\d{2}-\d{2}$/.test(value) ? value : "";
}

export function validGrade(value: string | null): GradeFilter {
  return value && (GRADE_FILTER_VALUES as readonly string[]).includes(value) ? (value as GradeFilter) : "";
}

export function matchesGradeFilter(item: PreSpecListItem, grade: GradeFilter): boolean {
  if (!grade) return true;
  if (grade === GRADE_NONE_LABEL) return item.grade === null;
  return item.grade === grade;
}

/** 서버 `GET /api/pre-specs`의 `auto_preparation_status` 질의 인자 허용값 8종. */
export const AUTO_PREPARATION_FILTER_VALUES = [
  "not_applicable",
  "waiting_attachments",
  "bundle_draft",
  "bundle_ready",
  "overview_running",
  "deep_review_started",
  "deep_review_ready_for_click",
  "blocked",
] as const;

export function validAutoPreparationStatus(value: string | null): PreSpecAutoPreparationStatus | "" {
  return value && (AUTO_PREPARATION_FILTER_VALUES as readonly string[]).includes(value)
    ? value as PreSpecAutoPreparationStatus
    : "";
}

/** 서버 `GET /api/pre-specs`의 추적 결정 대기 허용값. */
export function validTrackingDecision(value: string | null): "pending" | "" {
  return value === "pending" ? "pending" : "";
}

/** 추적 결정 대기 — 신규이면서 사람이 아직 고르지 않은 건. `미확인`(null)과
 * 사람이 고른 `미선택`을 모두 대기로 본다 — 둘 다 결정이 남은 상태다. */
export function matchesTrackingDecision(item: PreSpecListItem, filter: "pending" | ""): boolean {
  if (!filter) return true;
  return item.origin === "신규" && (item.tracking_status === null || item.tracking_status === "미선택");
}

export function validView(value: string | null): ViewKey {
  return validOverviewView(value);
}

export function viewOf(key: ViewKey): ViewDefinition {
  return VIEWS.find((view) => view.key === key) ?? VIEWS[0];
}

export function matchesView(item: PreSpecListItem, key: ViewKey): boolean {
  const statuses = viewOf(key).statuses;
  if (statuses === null) return true;
  return statuses.includes(item.overview_review_status);
}

export function nextActionLabel(value: PreSpecListItem["next_action"]): string | null {
  return value ? PRE_SPEC_NEXT_ACTION_LABEL[value] ?? null : null;
}

/** 목록과 상세에서 같은 서버 값을 같은 문장으로 옮기는 순수 표시 도우미. */
export function budgetLabel(value: number | null): string {
  return value === null || Number.isNaN(value) ? "예산 미확인" : formatCompactPrice(value);
}

export function exactBudget(value: number | null): string {
  return value === null || Number.isNaN(value) ? "예산 미확인" : `${formatNumber(value)}원`;
}

export function trackingLabel(item: PreSpecListItem): string {
  if (item.opportunity_id === null) return "사업기회 미연결";
  return item.tracking_status ?? "미확인";
}

export function overviewTokenColor(status: PreSpecOverviewReviewStatus | null): "red" | "orange" | "default" {
  if (status === "failed") return "red";
  if (status === "needs_human_review") return "orange";
  return "default";
}

export function attachmentAttention(item: PreSpecListItem): string | null {
  const parts: string[] = [];
  if (item.document["차단"] > 0) parts.push(`차단 ${item.document["차단"]}`);
  if (item.document["실패"] > 0) parts.push(`실패 ${item.document["실패"]}`);
  return parts.length > 0 ? `첨부 ${parts.join(" · ")}` : null;
}

export function titleOf(item: PreSpecListItem): string {
  return item.title?.trim() || "사업명 미확인";
}

export function agencyOf(item: PreSpecListItem): string {
  return item.agency?.trim() || "발주기관 미확인";
}

export function overviewStatusLabel(status: PreSpecOverviewReviewStatus | null): string {
  return status === null ? PRE_SPEC_OVERVIEW_NOT_STARTED_LABEL : PRE_SPEC_OVERVIEW_STATUS_LABEL[status];
}

export function originLabel(value: PreSpecListItem["origin"]): string {
  if (value === null) return "구분 미확인";
  return originOf(value) === "추적" ? "발주계획 연계" : "독립 발견";
}

export function swRowNote(value: string | null): string | null {
  if (value === "Y") return null;
  return value === null ? "SW 미확인" : `SW ${value}`;
}
