import { formatCompactPrice } from "./deadline";
import { formatNumber } from "./format";
import { PRE_SPEC_TERM } from "./glossary";
import { originOf } from "./opportunity";
import {
  PRE_SPEC_OVERVIEW_NOT_STARTED_LABEL,
  PRE_SPEC_OVERVIEW_STATUS_LABEL,
} from "./preSpecOverviewStatus";
import type { MarkTone } from "../components/common/Marks";
import type {
  PreSpecAutoPreparationStatus,
  PreSpecCompanyFitGroup,
  PreSpecListItem,
  PreSpecDeadlineStatus,
  PreSpecOverviewView,
  PreSpecOverviewReviewStatus,
  PreSpecSort,
  PreSpecWorkspace,
} from "./types";

// 등급 필터는 2026-11-19에 사전규격 화면에서 내려갔다(사전규격 단계 수정안 §3 B — C-1
// 공고 판정을 다시 돌리지 않으므로 등급은 전부 `판정 없음`이다). 서버의 `grade`·
// `display_grade` 질의 인자는 그대로 있고 화면만 보내지 않는다.

export type WorkspaceKey = PreSpecWorkspace;
export type ViewKey = PreSpecOverviewView;

interface WorkspaceDefinition {
  key: WorkspaceKey;
  label: string;
  description: string;
  defaultSort: PreSpecSort;
}

interface ViewDefinition {
  key: ViewKey;
  label: string;
  /** `null`이면 전체(상태로 좁히지 않음). */
  statuses: readonly (PreSpecOverviewReviewStatus | null)[] | null;
  description: string;
}

export const WORKSPACES: readonly WorkspaceDefinition[] = [
  {
    key: "actionable",
    label: PRE_SPEC_TERM.actionable,
    description: "개요를 읽고 추적을 정할 건(개요 완료·개요 확인 필요, 추적 결정 없음)",
    // PS-01: 회사 핏 부합 → 판단 보류 → 판정 전 → 불일치, 그룹 안은 마감 임박순(서버 정렬).
    defaultSort: "fit",
  },
  {
    key: "needs_check",
    label: PRE_SPEC_TERM.needsCheck,
    description: "개요가 실패·취소로 끝났거나 문서 준비가 멈춘 건(추적 결정 없음)",
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
  { value: "fit", label: "회사 핏순" },
];

export function validSort(value: string | null): PreSpecSort | "" {
  return SORT_OPTIONS.some((option) => option.value === value) ? value as PreSpecSort : "";
}

/** 목록 회사 핏 그룹(PS-01 C6) 표시. 그룹은 서버가 정하고 화면은 옮기기만 한다. */
export const COMPANY_FIT_GROUP_LABEL: Record<PreSpecCompanyFitGroup, string> = {
  matched: "부합",
  unknown: "판단 보류",
  pending: "판정 전",
  mismatch: "불일치",
};

/** 불일치는 실패가 아니고 판정 전도 문제가 아니다 — 성공·실패 의미색을 쓰지 않는다. 문구가 뜻을 진다. */
const COMPANY_FIT_GROUP_TONE: Record<PreSpecCompanyFitGroup, MarkTone> = {
  matched: "accent",
  unknown: "warning",
  pending: "neutral",
  mismatch: "neutral",
};

/** 필터·라벨 순서는 회사 핏순과 같다. */
export const COMPANY_FIT_GROUP_OPTIONS: readonly PreSpecCompanyFitGroup[] = ["matched", "unknown", "pending", "mismatch"];

export function validCompanyFitGroup(value: string | null): PreSpecCompanyFitGroup | "" {
  return COMPANY_FIT_GROUP_OPTIONS.includes(value as PreSpecCompanyFitGroup) ? value as PreSpecCompanyFitGroup : "";
}

/** 요약이 없으면(확장 미등록) 서버는 그 공고를 `pending`으로 정렬·필터한다. 표시도 같은 그룹을 쓴다. */
export function companyFitGroupOf(item: Pick<PreSpecListItem, "company_fit">): PreSpecCompanyFitGroup {
  return item.company_fit?.group ?? "pending";
}

export function companyFitMark(item: Pick<PreSpecListItem, "company_fit">): { label: string; tone: MarkTone } {
  const group = companyFitGroupOf(item);
  return { label: COMPANY_FIT_GROUP_LABEL[group], tone: COMPANY_FIT_GROUP_TONE[group] };
}

export const DEADLINE_STATUS_OPTIONS: readonly { value: PreSpecDeadlineStatus; label: string }[] = [
  { value: "open", label: "마감 전" },
  { value: "passed", label: "마감 경과" },
  { value: "unknown", label: "마감 미확인" },
];

/** 검토할 항목·확인 필요의 마감 구간 전환(ADR-0064, 2026-11-19 확인 필요에도 적용).
 * 화면은 `current`·`passed` 둘만 쓰고 서버 기본값 `all`은 고르지 않는다 — 두 보기의
 * 기본 시야는 `마감 전·미확인`이다.
 * `마감 미확인`(`deadline_at`이 null)은 `current` 쪽에 남으며 경과로 접지 않는다. */
export const DEADLINE_SCOPE_OPTIONS = [
  { value: "current", label: "마감 전·미확인" },
  { value: "passed", label: "마감 경과" },
] as const;

export function validDeadlineScope(value: string | null): "current" | "passed" {
  return value === "passed" ? "passed" : "current";
}

export const TRACKING_STATUS_OPTIONS = ["계속 추적", "보류", "종료", "미선택"] as const;

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

/** 서버 `GET /api/pre-specs`의 `auto_preparation_status` 질의 인자 허용값 8종. */
export const AUTO_PREPARATION_FILTER_VALUES = [
  "not_applicable",
  "waiting_attachments",
  "bundle_draft",
  "bundle_ready",
  "overview_running",
  "deep_review_started",
  "overview_settled",
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

function viewOf(key: ViewKey): ViewDefinition {
  return VIEWS.find((view) => view.key === key) ?? VIEWS[0];
}

export function matchesView(item: PreSpecListItem, key: ViewKey): boolean {
  const statuses = viewOf(key).statuses;
  if (statuses === null) return true;
  return statuses.includes(item.overview_review_status);
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

export function overviewStatusTone(status: PreSpecOverviewReviewStatus | null): "error" | "warning" | "neutral" {
  if (status === "failed") return "error";
  if (status === "needs_human_review") return "warning";
  return "neutral";
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
