import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { KeyboardEvent as ReactKeyboardEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, Navigate, useSearchParams } from "react-router-dom";
import { searchKey } from "../lib/search";
import { orderPlanViewTotalQuery } from "../lib/defaultViewCounts";
import { StatusMark } from "../components/common/Marks";
import { Banner } from "@astryxdesign/core/Banner";
import { Button } from "@astryxdesign/core/Button";
import { DialogHeader } from "@astryxdesign/core/Dialog";
import { Dialog } from "../components/common/WorkspaceDialog";
import { SegmentedControl, SegmentedControlItem } from "@astryxdesign/core/SegmentedControl";
import { TextArea } from "@astryxdesign/core/TextArea";
import { TextInput } from "@astryxdesign/core/TextInput";
import { MultiSelector, type MultiSelectorSelectedItem } from "@astryxdesign/core/MultiSelector";
import { Selector } from "@astryxdesign/core/Selector";
import { Text } from "@astryxdesign/core/Text";
import { ConfirmDecisionDialog, trackingEndConfirmContent } from "../components/common/ConfirmDecisionDialog";
import { EmptyState } from "../components/common/EmptyState";
import { PageHeaderActions, PageHeaderTabs } from "../components/common/PageHeaderActions";
import { requestActorInput, setRememberedActorName, useRememberedActorName } from "../components/common/ActorField";
import { usePageHeader } from "../components/shell/PageHeaderContext";
import { useRowKeyboardNavigation } from "../components/common/useRowKeyboardNavigation";
import { useUnsavedGuard } from "../components/common/useUnsavedGuard";
import { Toast } from "../components/common/Toast";
import { useToast } from "../components/common/useToast";
import {
  TRACKING_OTHER_REASON,
  TRACKING_SAVE_FAILED,
  trackingInputBlockedReason,
  trackingReasonValue,
  trackingSavedMessage,
} from "../components/common/TrackingDecisionForm";
import { RecordTable } from "../components/common/RecordTable";
import { useListSelection } from "../components/common/useListSelection";
import {
  ListPagerControls,
  ReviewDecisionAction,
  ReviewFilterTextInput,
  ReviewRevisionHistory,
  SelectionToolbar,
  SplitWorkspace,
} from "../components/common/ReviewPrimitives";
import { SourceRunContextLine, SourceRunFilter } from "../components/common/SourceRunFilter";
import {
  AppliedFilterTokens,
  formatCount,
  type AppliedFilter,
  WorkspaceAdvancedToggle,
  WorkspaceFilterAdvanced,
  WorkspaceFilterGroup,
  WorkspaceFilterBar,
  WorkspaceFilterContext,
  WorkspaceFilterLine,
  WorkspaceFrame,
  WorkspaceFilterTools,
  WorkspaceSearch,
  WorkspaceViewTabs,
} from "../components/common/WorkspaceFilters";
import { buildSourceRunOptions } from "../lib/runOptions";
import { formatCompactPrice } from "../lib/deadline";
import { ORDER_PLAN_BULK_END_MAX_SELECTION, api } from "../lib/api";
import { describeApiError } from "../lib/apiErrors";
import { generateRequestId } from "../lib/requestId";
import {
  ORDER_PLANS_SELECTION_STORAGE_KEY,
  orderPlansFilterFingerprint,
} from "../lib/listSelection";
import {
  getPendingOrderPlanBulkTrackingAction,
  hasPendingOrderPlanBulkTrackingRequest,
  OrderPlanBulkTrackingDialog,
} from "../components/order-plans/OrderPlanBulkTrackingDialog";
import { OrderPlanDetailPane } from "../components/order-plans/OrderPlanDetailPane";
import { orderPlanColumns } from "../components/order-plans/OrderPlanListRow";
import { scopeLabel } from "../components/order-plans/orderPlanDialogShared";
import {
  TRACKING_REASONS,
  formatMoment,
  textOrUnknown,
  trackingAvailability,
} from "../components/order-plans/orderPlanFormat";
import {
  ORDER_PLAN_NULL_LABEL,
  ORDER_PLAN_FEEDBACK_RELEVANCE_LABEL,
  ORDER_PLAN_PRIORITY_LABEL,
  ORDER_PLAN_RELEVANCE_LABEL,
  ORDER_PLAN_STAGE1_LABEL,
  ORDER_PLAN_TRACKING_NONE_LABEL,
  orderPlanLabel,
} from "../lib/glossary";
import type {
  C2DailyTriggerStateResponse,
  OrderPlanFeedbackPriority,
  OrderPlanListItem,
  OrderPlanListQuery,
  OrderPlanListScope,
  OrderPlanRelevance,
  OrderPlanScreeningExecutionListResponse,
  OrderPlanScreeningExecutionSummary,
  OpportunityTrackingStatus,
} from "../lib/types";
import "../styles/order-plans.css";

const PAGE_SIZE = 100;
const EXECUTION_PAGE_SIZE = 500;
function orderPlanPageKey(params: OrderPlanListQuery) {
  return ["order-plan-c2", "list", { ...params, q: searchKey(params.q) }] as const;
}

const SAVED_VIEWS_STORAGE_KEY = "bidops.order-plans.views";

/**
 * 두 값만 **탭 세션** 동안 기억한다(localStorage가 아니다).
 *
 * - 담당자 이름은 감사 표식이지 인증이 아니다. 한 번 적고 여러 건에 다시 쓰는 값이므로
 *   화면을 오갈 때마다 다시 치게 하지 않는다. 브라우저를 닫으면 사라진다.
 * - 직전 사유는 **다시 쓰기 단추의 후보**일 뿐이다. 드롭다운은 여전히 빈 값에서 시작하고
 *   저장에 성공하면 비워진다(PRD §3.3) — 사람이 누를 때에만 채워진다.
 */
const LAST_REASON_STORAGE_KEY = "bidops.order-plans.lastTrackingReason";
/**
 * 이 탭에서 저장에 성공한 추적 결정의 영수증(최종 시안 `오늘 정한 발주계획`). 서버가 돌려준 추적 상태·사유만
 * 담고 다시 계산하지 않는다. 탭을 닫으면 사라지며, 저장소에 닿지 못하면 목록을 그리지 않는다.
 */
const DECIDED_RECEIPTS_STORAGE_KEY = "bidops.order-plans.decidedReceipts";

interface DecidedReceipt {
  order_plan_pk: number;
  opportunity_id: number;
  title: string | null;
  agency_name: string | null;
  budget_amount: number | null;
  tracking_status: OpportunityTrackingStatus;
  tracking_reason: string | null;
  saved_at: string | null;
}

function loadReceipts(): DecidedReceipt[] | null {
  try {
    const raw = window.sessionStorage.getItem(DECIDED_RECEIPTS_STORAGE_KEY);
    if (!raw) return [];
    const parsed: unknown = JSON.parse(raw);
    return Array.isArray(parsed)
      ? parsed.filter((entry): entry is DecidedReceipt => typeof entry === "object" && entry !== null && typeof (entry as DecidedReceipt).order_plan_pk === "number" && typeof (entry as DecidedReceipt).opportunity_id === "number")
      : [];
  } catch {
    return null;
  }
}

function saveReceipts(receipts: DecidedReceipt[]): boolean {
  try {
    window.sessionStorage.setItem(DECIDED_RECEIPTS_STORAGE_KEY, JSON.stringify(receipts));
    return true;
  } catch {
    return false;
  }
}

type RelevanceToken = "relevant" | "uncertain" | "not_relevant" | "null";
type Stage1Token = "selected" | "filtered_out" | "failed" | "rejected" | "null";
type FeedbackToken = "has" | "none";
/**
 * 추적 상태 축. `none`은 소유 사업기회를 확인하지 못한 행(`tracking`이 null이거나 없음)이며
 * `미선택`이 아니다. 서버 `tracking_status` 필터도 그런 행을 어느 상태에도 넣지 않는다.
 */
type TrackingToken = OpportunityTrackingStatus | "none";
/** 기본 검토 화면 밖으로 옮긴 보조 표시. 한 번에 하나만 연다. */
type SecondaryDialog = "feedback";

const RELEVANCE_TOKENS: readonly RelevanceToken[] = ["relevant", "uncertain", "not_relevant", "null"];
const STAGE1_TOKENS: readonly Stage1Token[] = ["selected", "filtered_out", "failed", "rejected", "null"];
const FEEDBACK_TOKENS: readonly FeedbackToken[] = ["has", "none"];
const TRACKING_TOKENS: readonly TrackingToken[] = ["미선택", "계속 추적", "보류", "종료", "none"];
const AXIS_KEYS = ["qwen", "stage1", "feedback", "tracking", "issue", "unjudged", "q"] as const;

interface FilterAxes {
  qwen: RelevanceToken[];
  stage1: Stage1Token[];
  feedback: FeedbackToken[];
  tracking: TrackingToken[];
  issue: boolean;
  /**
   * `모델 미판정` 보기(2026-11-18 수정안 3B): 1차 선별 `순위 밖`(filtered_out) **또는** 판정 실패.
   * 축 안 OR·축끼리 AND 규칙으로는 두 축을 OR로 묶을 수 없어 별도 축(URL `unjudged=yes`)으로 둔다.
   */
  unjudged: boolean;
}

interface Preset {
  key: "relevant" | "uncertain" | "unjudged" | "all";
  label: string;
  description: string;
  axes: FilterAxes;
}

/**
 * 기본 보기는 `관련` 탭이다(2026-11-18 설계고도화안 A-6). 모델 판단 `relevant` AND 추적 상태
 * `미선택`. 이전 기본 보기는 `relevant`·`uncertain`을 한 목록에 섞어 하루 검토량이 임계 80건을
 * 넘었다 — 모델 판정·정책은 그대로 두고 **보기만 나눈다**. `불확실`(모델 `uncertain`, 화면 라벨도
 * `불확실` — C-6)은 바로 옆 탭이며, 두 탭의 합은 대시보드 `order_plan_pending`(관련·불확실 AND
 * 미선택, contracts.md)과 같다. 옛 `검토 대상` 탭이 URL에 적던 축(`qwen=relevant,uncertain&
 * tracking=미선택`)과 저장된 뷰는 그대로 같은 행을 보인다 — 탭 이름만 없어졌다.
 * `stage1_status=selected`는 따로 걸지 않는다 — 모델 relevance가 있는 행은 BM25 선정 행뿐이다.
 */
const DEFAULT_VIEW_AXES: FilterAxes = { qwen: ["relevant"], stage1: [], feedback: [], tracking: ["미선택"], issue: false, unjudged: false };
const UNCERTAIN_VIEW_AXES: FilterAxes = { qwen: ["uncertain"], stage1: [], feedback: [], tracking: ["미선택"], issue: false, unjudged: false };
const UNJUDGED_VIEW_AXES: FilterAxes = { qwen: [], stage1: [], feedback: [], tracking: [], issue: false, unjudged: true };
const ALL_VIEW_AXES: FilterAxes = { qwen: [], stage1: [], feedback: [], tracking: [], issue: false, unjudged: false };

/**
 * 보기 탭은 세 단 + 전체다(2026-11-18 수정안 3B): `관련`(필수 검토) → `불확실`(훑어보기) →
 * `모델 미판정` → `전체`. 탭 이름은 짧게 두고 역할은 목록 머리 설명 줄(`filterMeaning`)이 말한다.
 * 옛 탭 `1차 선별 제외`(`stage1=filtered_out`)·`선별 실패`(`issue=yes`)의 주소는 화면에 들어올 때
 * `모델 미판정`으로 옮긴다(`legacyUnjudgedViewSearch`).
 */
const PRESETS: Preset[] = [
  { key: "relevant", label: "관련", description: "필수 검토 · 모델이 관련으로 판단", axes: DEFAULT_VIEW_AXES },
  { key: "uncertain", label: "불확실", description: "훑어보기 · 모델이 불확실로 판단", axes: UNCERTAIN_VIEW_AXES },
  { key: "unjudged", label: "모델 미판정", description: "모델이 판정하지 않은 건 · 1차 순위순", axes: UNJUDGED_VIEW_AXES },
  { key: "all", label: "전체", description: "누적 또는 선택한 수집 회차 전체", axes: ALL_VIEW_AXES },
];

/** 지금 주소가 옛 탭(`1차 선별 제외`·`선별 실패`) 하나와 같은가. 축 하나만 걸리고 나머지는 비어 있어야 한다. */
function isLegacyUnjudgedView(params: URLSearchParams): boolean {
  if (!["stage1", "issue"].some((key) => params.has(key))) return false;
  if (params.get("unjudged") || (params.get("q") ?? "").trim()) return false;
  if (["qwen", "feedback", "tracking"].some((key) => (params.get(key) ?? "").trim() !== "")) return false;
  const stage1 = parseTokenSet(params.get("stage1"), STAGE1_TOKENS);
  const issue = params.get("issue") === "yes";
  const onlyFilteredOut = !issue && stage1.size === 1 && stage1.has("filtered_out");
  const onlyIssue = issue && stage1.size === 0;
  return onlyFilteredOut || onlyIssue;
}

/** 옛 탭 주소를 `모델 미판정` 보기 주소로 바꾼다. 축만 바꾸고 회차·첫 수집 창·선택 행은 그대로 둔다. */
function legacyUnjudgedViewSearch(params: URLSearchParams): URLSearchParams {
  const next = new URLSearchParams(params);
  for (const key of ["qwen", "stage1", "feedback", "tracking", "issue"]) next.set(key, "");
  next.set("unjudged", "yes");
  next.set("q", "");
  next.delete("offset");
  return next;
}

interface SavedView {
  id: string;
  name: string;
  search: string;
  createdAt: string;
}

/**
 * 배너는 활성화된 판정 기준이 있는데 자동 실행이 꺼져 있을 때만 둔다(spec §11 마지막 문단).
 *
 * **"오늘 돌지 않았습니다"라고 말하지 않는다**(0921 명세 §3.1) — `daily-trigger` 응답에는
 * 오늘 실행 여부가 없고 스위치 상태만 있다. 꺼진 사유(환경 설정·digest·컨테이너)는
 * 운영 화면(`/order-plan-policies`)이 이미 갖고 있으므로 실무 화면에서는 뺀다.
 */
function DailyTriggerOffBanner({ state }: { state: C2DailyTriggerStateResponse }) {
  if (state.policy_version === null || state.effective_enabled) return null;
  return (
    <Banner
      status="warning"
      title="자동 선별이 꺼져 있어요"
      description="새 발주계획이 판정되지 않을 수 있어요."
      collapsible={false}
      endContent={<Link className="c2l-scope-link" to="/order-plan-policies">운영 화면에서 확인 →</Link>}
    />
  );
}

/**
 * 필터 축 값의 화면 라벨(ADR-0066 결정 3). `null` 토큰은 "서버가 값을 주지 않음"이고
 * 표에 없는 값(서버가 새 enum을 준 경우)은 바꾸거나 숨기지 않고 원문 그대로 보인다.
 */
function axisValueLabel(labels: Readonly<Record<string, string>>): (token: string) => string {
  return (token) => (token === "null" ? ORDER_PLAN_NULL_LABEL : orderPlanLabel(labels, token));
}

const relevanceFilterLabel = axisValueLabel(ORDER_PLAN_RELEVANCE_LABEL);
const stage1FilterLabel = axisValueLabel(ORDER_PLAN_STAGE1_LABEL);

function formatFilterValues(items: MultiSelectorSelectedItem[]) {
  return items.map((item) => item.label).join(" · ");
}

/** 사람 판단 수정의 관련성. 모델 판단(`불확실`)과 달리 business-rules의 `판단 보류`를 쓴다(C-6). */
function relevanceLabel(value: OrderPlanRelevance): string {
  return orderPlanLabel(ORDER_PLAN_FEEDBACK_RELEVANCE_LABEL, value);
}

/** 우선순위를 고르지 않은 것(`null`)은 `미지정`이며 값이 없는 것과 다르게 적지 않는다. */
function priorityLabel(value: OrderPlanFeedbackPriority | null): string {
  return value === null ? "미지정" : orderPlanLabel(ORDER_PLAN_PRIORITY_LABEL, value);
}

/** Only a collected absolute HTTP(S) URL can become an external navigation link. */
function safeExternalUrl(value: string | null | undefined): string | null {
  if (!value) return null;
  try {
    const url = new URL(value);
    return ["https:", "http:"].includes(url.protocol) && !url.username && !url.password ? url.href : null;
  } catch {
    return null;
  }
}

function parseTokenSet<T extends string>(raw: string | null, allowed: readonly T[]): Set<T> {
  const set = new Set<T>();
  if (!raw) return set;
  for (const part of raw.split(",")) {
    const trimmed = part.trim();
    if ((allowed as readonly string[]).includes(trimmed)) set.add(trimmed as T);
  }
  return set;
}

function serializeTokens(values: Iterable<string>): string {
  return Array.from(values).join(",");
}

/**
 * `first_observed_from`은 **URL로만 들어오는 축**이다(S1). 대시보드 `새 관련
 * 발주계획` 패널이 자기 목록 호출과 같은 창으로 이 화면을 열기 위한 것이고, 상세
 * 필터에 새 컨트롤을 만들지 않는다. 형식이 아니면 보내지 않는다 — 422를 받는 대신
 * 창을 걸지 않은 목록이 된다. 날짜의 실재 여부는 서버가 본다.
 */
function parseFirstObservedFrom(value: string | null): string | null {
  const trimmed = value?.trim() ?? "";
  return /^\d{4}-\d{2}-\d{2}$/.test(trimmed) ? trimmed : null;
}

/** 첫 수집 창 줄의 표기. 회차 라벨과 같이 연도를 생략한 `MM-DD`다. */
function firstObservedLabel(value: string): string {
  return `${value.slice(5)} 이후 첫 수집`;
}

function parseOrderPlanPk(value: string | null): number | null {
  if (value === null || !/^\d+$/.test(value)) return null;
  const parsed = Number(value);
  return Number.isSafeInteger(parsed) && parsed > 0 ? parsed : null;
}

function setEqualsArray<T>(set: Set<T>, values: readonly T[]): boolean {
  return set.size === values.length && values.every((value) => set.has(value));
}

function loadSavedViews(): SavedView[] {
  try {
    const raw = window.localStorage.getItem(SAVED_VIEWS_STORAGE_KEY);
    if (!raw) return [];
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter((item): item is SavedView =>
      Boolean(item) && typeof (item as SavedView).id === "string" && typeof (item as SavedView).name === "string" && typeof (item as SavedView).search === "string");
  } catch {
    return [];
  }
}

function persistSavedViews(views: SavedView[]): void {
  try {
    window.localStorage.setItem(SAVED_VIEWS_STORAGE_KEY, JSON.stringify(views));
  } catch {
    /* localStorage 접근 불가는 화면 동작을 막지 않는다 */
  }
}

/** 값이 없거나 sessionStorage에 닿을 수 없으면 빈 문자열이다(기억한 적 없음). */
function loadSessionValue(key: string): string {
  try {
    return window.sessionStorage.getItem(key) ?? "";
  } catch {
    return "";
  }
}

function saveSessionValue(key: string, value: string): void {
  try {
    if (value) window.sessionStorage.setItem(key, value);
    else window.sessionStorage.removeItem(key);
  } catch {
    /* sessionStorage 접근 불가는 화면 동작을 막지 않는다 */
  }
}

async function fetchAllExecutions(signal: AbortSignal): Promise<OrderPlanScreeningExecutionListResponse> {
  const first = await api.getOrderPlanScreeningExecutions({ limit: EXECUTION_PAGE_SIZE, offset: 0 }, { signal });
  const items = [...first.items];
  const pageSize = first.limit > 0 ? first.limit : EXECUTION_PAGE_SIZE;
  while (items.length < first.total) {
    const page = await api.getOrderPlanScreeningExecutions({ limit: pageSize, offset: items.length }, { signal });
    if (!page.items.length) break;
    items.push(...page.items);
  }
  return { ...first, items, offset: 0 };
}

/** 실행 둘 중 더 최근인 것. 끝난 시각이 없으면 대기 시각으로 잰다(두 선택이 같은 순서를 쓴다). */
function isMoreRecent(item: OrderPlanScreeningExecutionSummary, latest: OrderPlanScreeningExecutionSummary): boolean {
  const latestAt = Date.parse(latest.finished_at ?? latest.queued_at);
  const itemAt = Date.parse(item.finished_at ?? item.queued_at);
  return itemAt > latestAt || (itemAt === latestAt && item.execution_id > latest.execution_id);
}

/**
 * **최근 실행의 건강 상태.** 상태와 무관하게 가장 최근 실행 하나를 고른다.
 *
 * 목록의 **판정 기준 실행**과 다른 값이다(0921 명세 §3.1, 독립 리뷰에서 확인된 결함).
 * 판정 기준은 서버가 정한다 — 회차 모드는 응답 `scope`의 실행, 누적 모드는 행마다 다른
 * `item.execution_id`다. 그 둘은 성공·부분 성공만 고르므로, 화면이 같은 규칙으로 실행
 * 상태를 말하면 "어제 성공 + 오늘 실패"가 어제의 `성공`으로 보여 실패가 사라진다.
 * 목록은 계속 마지막 성공 판정을 보여 주되, 최근 실행이 실패했다는 사실은 따로 알린다.
 */
function latestExecutionOfAny(items: OrderPlanScreeningExecutionSummary[]): OrderPlanScreeningExecutionSummary | null {
  return items.reduce<OrderPlanScreeningExecutionSummary | null>((latest, item) => (!latest || isMoreRecent(item, latest) ? item : latest), null);
}

/**
 * 사람이 조치해야 하는 실행 상태. 실행 중·대기는 문제가 아니므로 들어 있지 않고,
 * 부분 성공은 일부 결과가 빠진 것이므로 성공으로 접지 않는다(경고 ④).
 */
const EXECUTION_PROBLEM_STATUSES: ReadonlySet<string> = new Set(["실패", "중단됨", "중지 요청", "부분 성공"]);

/**
 * 상단 줄의 실행 표시. **문제가 있을 때만 그린다**(0921 명세 §3.1, 시안 M3 ②).
 *
 * 평상시(최근 실행 성공)에는 아무것도 그리지 않는다 — 실행 식별자·집계·모델 연결
 * 허용 여부는 운영 화면의 `발주계획 선별` 탭이 전문 그대로 진다. 조회 자체가 실패하면
 * 켜져 있다고 가정하지 않고 확인하지 못했다고 말한다.
 */
function ExecutionHealthChip({
  latest,
  isError,
  onRetry,
}: {
  latest: OrderPlanScreeningExecutionSummary | null;
  isError: boolean;
  onRetry: () => void;
}) {
  if (isError) {
    return (
      <span className="c2l-status-chip" role="status">
        <StatusMark mark={{ label: "선별 실행 상태를 확인하지 못했어요", tone: "error" }} />
        <Button label="다시 시도" size="sm" variant="ghost" onClick={onRetry} />
      </span>
    );
  }
  if (!latest || !EXECUTION_PROBLEM_STATUSES.has(latest.status)) return null;
  return (
    <span className="c2l-status-chip">
      <Link
        className="c2l-scope-link"
        to={`/runs?run=${encodeURIComponent(latest.source_run_id)}&execution=${encodeURIComponent(latest.execution_id)}`}
      >
        <StatusMark mark={{ label: `최근 선별 실행 ${latest.status} · 운영 화면에서 확인 →`, tone: "error" }} />
      </Link>
    </span>
  );
}

/**
 * 저장되지 않은 입력의 두 묶음. 잃는 조건이 서로 달라 한 값으로 합치지 않는다.
 *
 * - `FeedbackDraft`(사람 판단 수정)와 추적 결정 **사유**: 선택한 행이 바뀌면
 *   초기화된다. 그래서 **행을 바꾸는 조작**(행 선택·필터·페이지·넘기기)이 이 값을
 *   묻는다. 사유는 건마다 다시 고르는 값이므로 다음 건으로 넘어갈 때 비운다.
 * - 담당자 이름(`trackingActor`): 행이 바뀌어도 남고 화면을 떠날 때만 사라진다.
 *   그래서 **route 이동**만 이 값을 묻는다. 감사 표식이라 한 번 적고 여러 건에
 *   다시 쓰는 값이기 때문이다.
 */
interface FeedbackDraft {
  relevance: OrderPlanRelevance;
  priority: OrderPlanFeedbackPriority | "";
  memo: string;
}

const EMPTY_FEEDBACK_DRAFT: FeedbackDraft = { relevance: "uncertain", priority: "", memo: "" };

/**
 * 옛 보기 주소의 별칭(2026-11-18 수정안 3B). **화면에 들어올 때 한 번만** 본다 — 이미 열린 화면에서
 * 사람이 상세 필터로 같은 축(1차 선별 `순위 밖`만, `실패·거부만`)을 고르는 것은 그대로 그 필터다.
 * 별칭을 본문보다 먼저 풀어, 본문이 옛 축으로 한 번도 그려지지 않게 한다(선택 복원 fingerprint가
 * 옛 축으로 잡혔다 바로 바뀌어 선택을 지우는 일이 없다).
 */
export function OrderPlansPage() {
  const [searchParams] = useSearchParams();
  // 들어온 주소 하나만 본다. 렌더 중에 ref를 바꾸지 않으므로 StrictMode의 이중 렌더에도 같은 답이다.
  const [entrySearch] = useState(() => searchParams.toString());
  const [entryAlias] = useState(() => (isLegacyUnjudgedView(searchParams) ? legacyUnjudgedViewSearch(searchParams).toString() : null));
  // 본문이 한 번 그려진 뒤로는 별칭을 보지 않는다(상세 필터로 같은 축을 고른 경우).
  const workspaceShownRef = useRef(false);
  const showWorkspace = entryAlias === null || workspaceShownRef.current || searchParams.toString() !== entrySearch;
  useEffect(() => {
    if (showWorkspace) workspaceShownRef.current = true;
  }, [showWorkspace]);
  if (!showWorkspace) return <Navigate replace to={{ pathname: "/order-plans", search: `?${entryAlias}` }} />;
  return <OrderPlansWorkspace />;
}

function OrderPlansWorkspace() {
  const [searchParams, setSearchParams] = useSearchParams();
  const queryClient = useQueryClient();

  const qText = searchParams.get("q") ?? "";
  const [searchText, setSearchText] = useState(qText);
  const [dialog, setDialog] = useState<SecondaryDialog | null>(null);
  // A3: 시작·종료 두 단추가 같은 다이얼로그를 다른 mode로 연다. null이면 닫힘이다.
  const [bulkDialogMode, setBulkDialogMode] = useState<"start" | "end" | null>(null);
  const [bulkPending, setBulkPending] = useState(false);
  // A4: 일괄 추적 종료 직후 안내 한 줄. 다음 필터 변경·선택 변경 전까지 보인다.
  const [bulkEndNotice, setBulkEndNotice] = useState<number | null>(null);
  const [bulkRecoveryAvailable, setBulkRecoveryAvailable] = useState(() => hasPendingOrderPlanBulkTrackingRequest());
  const [advancedOpen, setAdvancedOpen] = useState(false);
  // ↑↓ 이동은 목록 `<ul>`에 리스너를 단다(window 전역이 아니다) — 상세 pane 입력의
  // 방향키가 같은 화면에서 서로 경쟁하지 않는다.
  const listRef = useRef<HTMLDivElement | null>(null);
  const [editingDecision, setEditingDecision] = useState<Exclude<OpportunityTrackingStatus, "미선택"> | null>(null);
  const trackingSectionRef = useRef<HTMLElement | null>(null);
  const [savedViews, setSavedViews] = useState<SavedView[]>(() => loadSavedViews());
  const [newViewName, setNewViewName] = useState("");
  const [isNamingView, setIsNamingView] = useState(false);

  // 사유는 자동으로 고르지 않는다. 빈 값이 기본이고, `기타`를 골라야 자유 입력이 열린다.
  // 같은 건에서 선택지를 왕복해도 적어 둔 자유 입력은 남긴다(시안 §3).
  const [reasonChoice, setReasonChoice] = useState("");
  const [customReason, setCustomReason] = useState("");
  // 담당자는 감사 표식이고 여러 건에 다시 쓰는 값이다. 사이드바 담당자 칸과 같은 한 값(`bidops.actorName`)을
  // 쓴다. 브라우저 저장소에 닿지 못하면 이 화면 안에서만 쓰는 값으로 남는다(지어내지 않는다).
  const rememberedActor = useRememberedActorName();
  const [localActor, setLocalActor] = useState("");
  const trackingActor = rememberedActor || localActor;
  // 이 탭에서 저장에 성공한 결정의 영수증. `null`이면 저장소에 닿지 못한 것이고 목록을 그리지 않는다.
  const [receipts, setReceipts] = useState<DecidedReceipt[] | null>(() => loadReceipts());
  // 저장에 성공한 마지막 사유. 드롭다운을 채우지 않고 `직전 사유 다시 쓰기` 단추만 만든다.
  const [lastReason, setLastReason] = useState(() => loadSessionValue(LAST_REASON_STORAGE_KEY));
  // 추적 `종료`만 되돌릴 수 없다. 확인 문구는 사전규격·사업 추적과 같은 자리에서
  // 만들어 세 화면이 다른 말을 하지 않게 한다.
  const [endConfirm, setEndConfirm] = useState<ReturnType<typeof trackingEndConfirmContent> | null>(null);
  // 결정 뒤의 안내는 **이동한 뒤의 건**에 붙는다. 선택이 바뀌면 사라지되, 그 이동을 만든
  // 결정의 안내는 남아야 하므로 어느 건에서 보일 문구인지를 함께 들고 다닌다.
  // 추적 결정 바의 안내 한 줄(넘기기·Ctrl+Enter 준비 안 됨). 저장 결과는 화면 알림(`toast`)이 진다.
  const [trackingMessage, setTrackingMessage] = useState<{ pk: number; text: string } | null>(null);
  const { toast, showToast, dismissToast } = useToast();
  /**
   * 방금 추적을 결정한 건. 기본 보기는 `미선택`만 보이므로 결정한 건은 다시 읽은 목록에서
   * 빠진다. 사람이 다른 건으로 옮기기 전까지는 그 건을 목록에 남겨 두어, 마지막 건에서
   * 결정했을 때 선택이 첫 행으로 튀지 않고 "이동하지 않습니다" 안내가 사실로 남게 한다.
   */
  const [retainedPk, setRetainedPk] = useState<number | null>(null);
  const [locateAfterSave, setLocateAfterSave] = useState<number | null>(null);

  const [relevance, setRelevance] = useState<OrderPlanRelevance>("uncertain");
  const [priority, setPriority] = useState<OrderPlanFeedbackPriority | "">("");
  const [memo, setMemo] = useState("");
  const [actorName, setActorName] = useState("");
  const [savedMessage, setSavedMessage] = useState<string | null>(null);
  // 저장 기준점. 저장에 성공하면 그때의 값이 새 기준이 되어 "저장되지 않은 입력"이
  // 풀린다. 값 자체는 그대로 두므로 사람은 방금 저장한 내용을 계속 볼 수 있다.
  const [feedbackBaseline, setFeedbackBaseline] = useState<FeedbackDraft>(EMPTY_FEEDBACK_DRAFT);

  const feedbackDirty = relevance !== feedbackBaseline.relevance
    || priority !== feedbackBaseline.priority
    || memo !== feedbackBaseline.memo;
  // 사유는 저장하면 다음 건으로 옮겨 가며 비워지므로 기준값은 늘 "빈 값"이다.
  const reasonDirty = reasonChoice !== "" || customReason.trim() !== "";
  /** 계약에 실을 사유. `기타`는 사람이 적은 문장 그대로이고 공백만 있으면 사유가 없다. */
  const trackingReason = trackingReasonValue(reasonChoice, customReason);

  const feedbackDraftSummary = [
    { label: "사람 판단 수정", value: `관련성 ${relevanceLabel(relevance)} · 우선순위 ${priorityLabel(priority || null)}` },
    { label: "메모", value: memo.trim() || "값 없음" },
  ];
  const reasonDraftSummary = [{ label: "선택 사유 초안", value: trackingReason || "직접 입력 미완료" }];
  const rowDraftSummary = [
    ...(feedbackDirty ? feedbackDraftSummary : []),
    ...(reasonDirty ? reasonDraftSummary : []),
    ...(bulkPending ? [{ label: "일괄 추적 요청", value: "저장 결과 확인 전까지 요청과 선택을 보호해요." }] : []),
  ];
  // route를 떠나면 사람 판단 수정 입력과 선택 사유가 사라진다. 담당자 이름은 이제 탭
  // 세션에 남으므로 잃는 값이 아니고, 그래서 이 확인의 조건에서 뺐다. 화면 안의
  // 이동(행·필터·페이지)은 경로가 바뀌지 않으므로 `pathname` 범위로 두고, 그 이동은
  // 아래에서 자기 문구로 묻는다.
  const guard = useUnsavedGuard(feedbackDirty || reasonDirty || bulkPending, {
    blockSpaNavigation: true,
    // During an in-flight bulk request even same-path back/forward/filter
    // navigation must be confirmed; the request binding is URL-contextual.
    scope: bulkPending ? "any" : "pathname",
    title: "발주계획 검토 화면을 떠나요",
    message: "저장하지 않은 입력 또는 확인 중인 일괄 요청이 있어요. 지금 이동하면 입력이 사라지거나 요청 결과를 놓칠 수 있어요.",
    summary: rowDraftSummary,
  });

  /**
   * 선택한 행이 바뀌는 조작. 사람 판단 수정 입력과 선택 사유가 사라지므로 그 둘만
   * 묻는다. 담당자 이름은 행이 바뀌어도 남으므로 여기서 잃는다고 말하지 않는다.
   */
  function withRowGuard(run: () => void) {
    guard.confirmDiscard(run, {
      dirty: feedbackDirty || reasonDirty || bulkPending,
      title: "다른 발주계획으로 이동해요",
      message: bulkPending
        ? "일괄 추적 요청이 결과 확인 중이에요. 이동하면 요청과 선택을 잃을 수 있어요."
        : "저장하지 않은 사람 판단 수정 입력과 선택 사유는 이 발주계획을 떠나면 사라져요. 담당자 이름은 그대로 남아요.",
      summary: rowDraftSummary,
    });
  }

  /**
   * 추적 결정을 저장하는 자리. 사유는 지금 저장되므로 잃는 것이 아니고, 사람 판단
   * 수정 입력만 다음 건으로 넘어가며 사라진다.
   */
  function withFeedbackGuard(run: () => void) {
    guard.confirmDiscard(run, {
      dirty: feedbackDirty,
      title: "다른 발주계획으로 이동해요",
      message: "저장하지 않은 사람 판단 수정 입력은 이 발주계획을 떠나면 사라져요. 담당자 이름은 그대로 남아요.",
      summary: feedbackDraftSummary,
    });
  }

  // 누락된 q와 q=는 둘 다 빈 검색어다. 이 둘 사이의 전환은 새로 입력한 검색어를 지우지 않는다.
  useEffect(() => setSearchText(qText), [qText]);

  const selectedParam = searchParams.get("selected");
  const selectedPk = parseOrderPlanPk(selectedParam);
  /**
   * `selected` is also written for ordinary row navigation. Remember whether it
   * was present when this page was entered so a deep link can be handled without
   * changing the normal list selection rules.
   */
  const initialSelectedParamRef = useRef<string | null>(selectedParam);
  const [deepLinkActive, setDeepLinkActive] = useState(() => initialSelectedParamRef.current !== null);
  const isExplicitDeepLink = deepLinkActive && selectedParam !== null;

  useEffect(() => {
    if (selectedParam === null && deepLinkActive) setDeepLinkActive(false);
  }, [deepLinkActive, selectedParam]);

  /**
   * 회차는 **감사용 보조 선택**이다(spec §7). URL에 회차가 없으면 누적 모드로 열고, 최신 회차를
   * 골라 URL에 박지 않는다 — 누적 목록이 기본이고, 회차를 고른 사람만 그 회차의 실행으로 좁힌다.
   * 사업 추적의 링크와 옛 `/order-plans/:pk` 북마크도 누적 목록 안에서 그 행을 고른다.
   */
  const sourceRunId = searchParams.get("source_run_id")?.trim() || null;
  /** 첫 수집 창. 회차와 같이 상세 필터의 한 축이며 URL이 소유한다(S1). */
  const firstObservedFrom = parseFirstObservedFrom(searchParams.get("first_observed_from"));
  const runsQuery = useQuery({
    queryKey: ["runs"],
    queryFn: () => api.getRuns(),
    enabled: advancedOpen || sourceRunId !== null,
    staleTime: 15_000,
  });
  const executionsQuery = useQuery({
    queryKey: ["order-plan-c2", "executions"],
    queryFn: ({ signal }) => fetchAllExecutions(signal),
    staleTime: 15_000,
  });
  const executions = executionsQuery.data?.items ?? [];
  const collectionRuns = useMemo(() => (runsQuery.data?.items ?? [])
    .filter((run) => run.kind === "order_plans" || run.kind === "mixed")
    .sort((a, b) => b.generated_at.localeCompare(a.generated_at)), [runsQuery.data]);
  const dailyTriggerQuery = useQuery({
    queryKey: ["order-plan-c2", "daily-trigger"],
    queryFn: ({ signal }) => api.getC2DailyTrigger({ signal }),
    staleTime: 15_000,
  });

  /**
   * 회차 옵션은 공용 조립기가 만든다(`lib/runOptions.ts`). 회차 목록에 없고 실행에만
   * 있는 회차는 날짜를 지어내지 않고 `수집 정보 없는 회차`로 남으며, URL에 걸린 회차가
   * 목록에 없어도 조용히 다른 회차로 바뀌지 않는다.
   */
  const runOptionSourceIds = executions.map((execution) => execution.source_run_id);
  const runOptions = buildSourceRunOptions({
    runs: collectionRuns,
    extraRunIds: runOptionSourceIds,
    selectedRunId: sourceRunId,
    isError: runsQuery.isError,
  });
  const selectedRunLabel = sourceRunId
    ? runOptions.find((option) => option.value === sourceRunId)?.label ?? "선택한 회차 (목록에 없음)"
    : null;

  /**
   * **회차는 기존 조건에 더한다**(시안 M1 승인 2026-09-21). 회차가 상세 필터의 한 축이
   * 되었으므로 다른 축과 같은 방식(교집합)으로 동작한다 — 회차를 고른다고 검색어·보기·
   * 다른 필터를 조용히 지우지 않는다. 범위가 바뀌므로 페이지만 처음으로 돌리고, 선택
   * 집합은 `selectionFingerprint`에 회차가 들어 있어 저절로 새로 시작한다.
   */
  function changeSourceRun(runId: string | null) {
    const next = runId?.trim() || null;
    if (next === sourceRunId) return;
    withRowGuard(() => {
      const params = new URLSearchParams(searchParams);
      if (next) params.set("source_run_id", next);
      else params.delete("source_run_id");
      params.delete("offset");
      setSearchParams(params);
    });
  }

  /** 첫 수집 창을 지운다. 회차 줄의 `모든 회차로`와 같이 그 축 하나만 푼다. */
  function clearFirstObservedFrom() {
    if (firstObservedFrom === null) return;
    withRowGuard(() => {
      const params = new URLSearchParams(searchParams);
      params.delete("first_observed_from");
      params.delete("offset");
      setSearchParams(params);
    });
  }

  const defaultEntry = !AXIS_KEYS.some((key) => searchParams.has(key));
  const urlQwen = parseTokenSet(searchParams.get("qwen"), RELEVANCE_TOKENS);
  const urlStage1 = parseTokenSet(searchParams.get("stage1"), STAGE1_TOKENS);
  const urlFeedback = parseTokenSet(searchParams.get("feedback"), FEEDBACK_TOKENS);
  const urlTracking = parseTokenSet(searchParams.get("tracking"), TRACKING_TOKENS);
  const issueOn = searchParams.get("issue") === "yes";
  const unjudgedOn = searchParams.get("unjudged") === "yes";
  const explicitPreset = qText ? undefined : PRESETS.find(({ axes }) => (
    setEqualsArray(urlQwen, axes.qwen)
    && setEqualsArray(urlStage1, axes.stage1)
    && setEqualsArray(urlFeedback, axes.feedback)
    && setEqualsArray(urlTracking, axes.tracking)
    && issueOn === axes.issue
    && unjudgedOn === axes.unjudged
  ));
  const offsetRaw = Number(searchParams.get("offset") ?? "0");
  const requestedOffset = Number.isSafeInteger(offsetRaw) && offsetRaw >= 0 ? Math.floor(offsetRaw / PAGE_SIZE) * PAGE_SIZE : 0;
  const presetOrder = explicitPreset?.key;
  const pageQuery: OrderPlanListQuery = {
    source_run_id: sourceRunId,
    first_observed_from: firstObservedFrom,
    review_order: defaultEntry ? "default" : presetOrder && presetOrder !== "all" ? presetOrder : "relevance",
    qwen_relevance: [...urlQwen].map((value) => value === "null" ? "missing" : value),
    stage1_status: [...urlStage1].map((value) => value === "null" ? "missing" : value),
    feedback_present: urlFeedback.size === 1 ? urlFeedback.has("has") : undefined,
    tracking_status: [...urlTracking].map((value) => value === "none" ? "missing" : value),
    issue: issueOn || undefined,
    unjudged: unjudgedOn || undefined,
    q: qText,
    limit: PAGE_SIZE,
    offset: requestedOffset,
    locate: isExplicitDeepLink ? selectedPk : locateAfterSave,
    retain: retainedPk === selectedPk ? retainedPk : null,
  };
  const listQuery = useQuery({
    queryKey: orderPlanPageKey(pageQuery),
    queryFn: ({ signal }) => api.getOrderPlans(pageQuery, { signal }),
    staleTime: 15_000,
  });
  const offset = listQuery.data?.offset ?? requestedOffset;
  const reviewPage = listQuery.data?.review_page;
  const viewCounts = reviewPage?.view_counts;
  useEffect(() => {
    if (sourceRunId || firstObservedFrom || !viewCounts) return;
    queryClient.setQueryData(orderPlanViewTotalQuery("relevant").queryKey, viewCounts.relevant);
    queryClient.setQueryData(orderPlanViewTotalQuery("uncertain").queryKey, viewCounts.uncertain);
  }, [firstObservedFrom, queryClient, sourceRunId, viewCounts]);
  /** 목록 응답의 범위. 불러오기 전에는 `undefined`, 회차에 완료 실행이 없으면 `null`이다. */
  const listScope: OrderPlanListScope | null | undefined = listQuery.data ? listQuery.data.scope : undefined;
  const isCumulative = sourceRunId === null;
  /**
   * 판정이 하나라도 있는 범위인지. 누적 범위에 실행이 하나도 없어(`policy_versions`가 비어) 판정이
   * 없거나 회차에 완료 실행이 없으면 기본 보기(관련 건만)가 모든 행을 숨기므로 전체를 보인다 —
   * 판정 없음을 비관련으로 읽지 않는다. 서버의 빈 목록은 대시보드의 `no_completed_execution`과 같은 사실이다.
   */
  const judgmentsAvailable = listScope != null
    && (listScope.mode === "run" || listScope.policy_versions.length > 0);
  // 실행 표시가 읽는 실행 범위. 회차 모드는 그 회차의 실행 전부다.
  // 누적 모드는 활성화된 적 있는 policy(`activated_policy_versions`)의 운영 실행만
  // 본다 — 측정 전용 실행이나 한 번도 활성화되지 않은 policy의 참조 실행을 "최근 운영 실행"처럼
  // 보이지 않는다. 판정 유무(`policy_versions`)가 아니라 활성화 이력으로 가르므로, 막 활성화한
  // policy의 첫 실행이 대기·실행 중·실패여도 칩에서 사라지지 않는다.
  const operationalExecutions = executions.filter((execution) => execution.purpose === "operational");
  const scopedExecutions = sourceRunId
    ? executions.filter((execution) => execution.source_run_id === sourceRunId)
    // 범위를 알기 전(목록 로딩 중)에는 비워 둔다 — 참조 실행이 한 프레임이라도 칩에 보이지 않게 한다.
    : operationalExecutions.filter((execution) => listScope?.mode === "cumulative" && listScope.activated_policy_versions.includes(execution.policy_version));
  /** 건강 상태를 말하는 실행(상태와 무관하게 최신 1건). 판정 기준 실행과 다를 수 있다. */
  const latestExecutionOverall = latestExecutionOfAny(scopedExecutions);

  // Keep the normal review default while resolving a selected row. Once the
  // target and list scope are known, the targeted reset effect below
  // removes only filters that hide that record (for example `not_relevant`).
  const isDefaultView = judgmentsAvailable && defaultEntry && !reviewPage?.target_filters_cleared;
  const qwenSet = isDefaultView ? new Set<RelevanceToken>(DEFAULT_VIEW_AXES.qwen) : urlQwen;
  const stage1Set = urlStage1;
  const feedbackSet = urlFeedback;
  const trackingSet = isDefaultView ? new Set<TrackingToken>(DEFAULT_VIEW_AXES.tracking) : urlTracking;
  /**
   * 첫 수집 창도 의미 필터이므로 바뀌면 선택을 비운다. 공용
   * `orderPlansFilterFingerprint`에는 아직 이 축이 없어 여기서 덧붙이며, **창이 없으면
   * 지금까지와 같은 문자열**이라 기존에 기억된 선택은 그대로 복원된다.
   */
  const baseFingerprint = orderPlansFilterFingerprint({
    sourceRunId,
    qwen: qwenSet,
    stage1: stage1Set,
    feedback: feedbackSet,
    tracking: trackingSet,
    issue: issueOn,
    q: qText,
  });
  // `모델 미판정` 축도 같은 방식으로 덧붙인다 — 꺼져 있으면 지금까지와 같은 문자열이다.
  const selectionFingerprint = `${baseFingerprint}${unjudgedOn ? "|unjudged" : ""}${firstObservedFrom ? `|first_observed_from:${firstObservedFrom}` : ""}`;
  // 기본 보기는 목록의 범위(`scope`)를 보고 정해진다. 범위를 알기 전에 선택을 복원하면
  // fingerprint가 바로 바뀌어 복원한 선택을 지운다.
  const selectionHydrationReady = !listQuery.isPending;
  const orderPlanSelection = useListSelection<number>({
    storageKey: ORDER_PLANS_SELECTION_STORAGE_KEY,
    filterFingerprint: selectionFingerprint,
    hydrationReady: selectionHydrationReady,
    // A selected URL target owns only active/source/page context. Checked
    // membership is an independent tab-session state and must still restore
    // when the browser reloads an automatically selected URL.
    restoreStoredState: true,
  });

  const activePreset = isDefaultView ? "relevant" : explicitPreset?.key ?? null;

  // 아래 네 함수는 확인 단계를 갖지 않는 원본이다. 확인은 사람이 누르는 자리
  // (`changeAxes`, `applyPreset`, `applySavedViewSearch`, `resetFilters`, 페이지 이동)가
  // 한 번만 건다. 원본끼리 겹쳐 부르면 같은 질문이 두 번 뜬다.
  function applyAxes(next: { qwen?: Set<RelevanceToken>; stage1?: Set<Stage1Token>; feedback?: Set<FeedbackToken>; tracking?: Set<TrackingToken>; issue?: boolean; unjudged?: boolean; q?: string }) {
    // A4: 필터가 바뀌면 일괄 종료 안내를 지운다. 이 함수는 축을 바꾸는 모든 경로의
    // 공용 원본이라 여기 한 곳에 둔다.
    setBulkEndNotice(null);
    const params = new URLSearchParams(searchParams);
    if (next.qwen) params.set("qwen", serializeTokens(next.qwen));
    if (next.stage1) params.set("stage1", serializeTokens(next.stage1));
    if (next.feedback) params.set("feedback", serializeTokens(next.feedback));
    if (next.tracking) params.set("tracking", serializeTokens(next.tracking));
    if (next.issue !== undefined) params.set("issue", next.issue ? "yes" : "");
    // 꺼진 `모델 미판정` 축은 주소에 남기지 않는다 — 다른 보기의 주소가 지금까지와 같다.
    if (next.unjudged !== undefined) {
      if (next.unjudged) params.set("unjudged", "yes");
      else params.delete("unjudged");
    }
    if (next.q !== undefined) params.set("q", next.q);
    params.delete("offset");
    setSearchParams(params, { replace: true });
    if (next.q !== undefined) orderPlanSelection.setListSearch(next.q);
  }

  /** 사람이 누르는 필터 축. 필터가 바뀌면 선택한 행도 바뀌므로 먼저 확인한다. */
  function changeAxes(next: { qwen?: Set<RelevanceToken>; stage1?: Set<Stage1Token>; feedback?: Set<FeedbackToken>; tracking?: Set<TrackingToken>; issue?: boolean; unjudged?: boolean; q?: string }) {
    withRowGuard(() => applyAxes(next));
  }

  function applySearch(next: string) {
    const raw = searchKey(next) ? next : "";
    const changed = searchKey(raw) !== searchKey(qText);
    const run = () => {
      const params = new URLSearchParams(searchParams);
      if (raw) params.set("q", raw);
      else params.delete("q");
      if (changed) params.delete("offset");
      setSearchParams(params, { replace: true });
      orderPlanSelection.setListSearch(raw);
      setSearchText(raw);
    };
    if (changed) withRowGuard(run);
    else run();
  }

  function applyPreset(presetKey: string) {
    const preset = PRESETS.find((item) => item.key === presetKey);
    if (!preset) return;
    withRowGuard(() => {
      applyAxes({
        qwen: new Set(preset.axes.qwen),
        stage1: new Set(preset.axes.stage1),
        feedback: new Set(preset.axes.feedback),
        tracking: new Set(preset.axes.tracking),
        issue: preset.axes.issue,
        unjudged: preset.axes.unjudged,
        q: "",
      });
      setSearchText("");
    });
  }

  function applySavedViewSearch(search: string) {
    withRowGuard(() => {
      // 옛 탭(`1차 선별 제외`·`선별 실패`)을 저장한 뷰도 주소 별칭과 같이 `모델 미판정`으로 연다.
      const storedParams = new URLSearchParams(search);
      const savedParams = isLegacyUnjudgedView(storedParams) ? legacyUnjudgedViewSearch(storedParams) : storedParams;
      const params = new URLSearchParams(searchParams);
      for (const key of AXIS_KEYS) {
        if (savedParams.has(key)) params.set(key, savedParams.get(key) ?? "");
        else params.delete(key);
      }
      params.delete("offset");
      setSearchParams(params, { replace: true });
      setSearchText(savedParams.get("q") ?? "");
    });
  }

  function resetFilters() {
    withRowGuard(() => {
      const params = new URLSearchParams(searchParams);
      for (const key of AXIS_KEYS) params.delete(key);
      // 회차도 상세 필터의 한 축이므로 초기화가 함께 지운다(명세 §2.1). 첫 수집 창도
      // 같은 자리의 축이라 같이 지운다(S1).
      params.delete("source_run_id");
      params.delete("first_observed_from");
      params.delete("offset");
      setSearchParams(params, { replace: true });
      setSearchText("");
    });
  }

  /** A4: 기본 보기가 빈 상태일 때 "종료한 건 보기" 동작. 추적 축만 `종료`로 바꾼다. */
  function viewEndedTracking() {
    withRowGuard(() => {
      applyAxes({
        qwen: new Set(),
        stage1: new Set(),
        feedback: new Set(),
        tracking: new Set(["종료"]),
        issue: false,
        unjudged: false,
        q: "",
      });
      setSearchText("");
    });
  }

  function saveCurrentAsView() {
    const name = newViewName.trim();
    if (!name) return;
    const params = new URLSearchParams();
    params.set("qwen", serializeTokens(qwenSet));
    params.set("stage1", serializeTokens(stage1Set));
    params.set("feedback", serializeTokens(feedbackSet));
    params.set("tracking", serializeTokens(trackingSet));
    params.set("issue", issueOn ? "yes" : "");
    if (unjudgedOn) params.set("unjudged", "yes");
    params.set("q", qText);
    const view: SavedView = { id: generateRequestId(), name, search: params.toString(), createdAt: new Date().toISOString() };
    const next = [...savedViews, view];
    setSavedViews(next);
    persistSavedViews(next);
    setNewViewName("");
    setIsNamingView(false);
  }

  function deleteSavedView(id: string) {
    const next = savedViews.filter((view) => view.id !== id);
    setSavedViews(next);
    persistSavedViews(next);
  }

  function selectRow(pk: number) {
    if (bulkPending) return;
    // 이미 보고 있는 건을 다시 고르는 것은 이동이 아니다. 여기서 막지 않으면 현재 행에서
    // Enter를 누르거나 다시 클릭할 때마다 "다른 발주계획으로 이동합니다" 확인이 뜬다.
    if (pk === selectedItem?.order_plan_pk) return;
    withRowGuard(() => {
      const params = new URLSearchParams(searchParams);
      params.set("selected", String(pk));
      setSearchParams(params, { replace: true });
      orderPlanSelection.setActiveId(pk);
    });
  }

  function changeOffset(nextOffset: number) {
    withRowGuard(() => {
      const params = new URLSearchParams(searchParams);
      params.set("offset", String(nextOffset));
      setSearchParams(params, { replace: true });
    });
  }

  const visibleItems = listQuery.data?.items ?? [];
  const total = listQuery.data?.total ?? 0;
  const presetCounts = reviewPage?.view_counts;
  const invalidSelectedParam = selectedParam !== null && selectedPk === null;
  const explicitTargetInFilteredItems = visibleItems.some((item) => item.order_plan_pk === selectedPk);
  const deepLinkFailed = isExplicitDeepLink && (
    invalidSelectedParam || listQuery.isError || reviewPage?.target_found === false
  );
  const selectedItem = invalidSelectedParam || deepLinkFailed ? null
    : visibleItems.find((item) => item.order_plan_pk === (selectedPk ?? orderPlanSelection.activeId))
      ?? (isExplicitDeepLink || locateAfterSave !== null ? null : visibleItems[0] ?? null);
  const selectedSourceUrl = selectedItem ? safeExternalUrl(selectedItem.source_url) : null;

  function toggleChecked(pk: number, checked: boolean) {
    const currentlyChecked = orderPlanSelection.selectedIdSet.has(pk);
    if (checked !== currentlyChecked) {
      orderPlanSelection.toggle(pk);
      // A4: 선택이 바뀌면 일괄 종료 안내를 지운다.
      setBulkEndNotice(null);
    }
  }

  // M7 ② — 사전규격 `selectCurrentPage`(spec §3.4)와 같은 규칙이다: **지금 이 페이지에
  // 그려진 행만** 기존 선택 뒤에 중복 없이 덧붙인다. 다른 페이지에서 고른 ID는 그대로
  // 남는다. 발주계획 선택에는 사전규격의 정렬 메타데이터가 없으므로 id만 넘긴다.
  const pageFullySelected = visibleItems.length > 0
    && visibleItems.every((item) => orderPlanSelection.selectedIdSet.has(item.order_plan_pk));
  function selectCurrentPage() {
    orderPlanSelection.selectMany(visibleItems.map((item) => item.order_plan_pk));
  }

  const handleBulkPendingChange = useCallback((pending: boolean) => {
    setBulkPending(pending);
    if (!pending) setBulkRecoveryAvailable(hasPendingOrderPlanBulkTrackingRequest());
  }, []);

  async function invalidateBulkQueries() {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["order-plan-c2", "list"] }),
      queryClient.invalidateQueries({ queryKey: ["opportunities"] }),
      queryClient.invalidateQueries({ queryKey: ["opportunity"] }),
      queryClient.invalidateQueries({ queryKey: ["opportunity-tracking-decisions"] }),
      queryClient.invalidateQueries({ queryKey: ["workload"] }),
      queryClient.invalidateQueries({ queryKey: ["pre-specs"] }),
    ]);
  }

  /**
   * 사람 판단 수정본은 **그 행의 결과를 낸 실행**에 붙는다(contracts.md "발주계획 목록 누적 모드").
   * 누적 모드에는 단일 실행이 없으므로 화면 전체의 최신 실행을 쓰지 않는다. 결과가 없는 행은
   * `null`이고 수정본을 만들지 않는다.
   */
  const feedbackExecutionId = selectedItem?.execution_id ?? null;
  /** 선택한 행의 결과를 낸 실행. 실행 기록 탭은 화면의 최신 실행이 아니라 이 실행을 보인다. */
  const rowExecution = feedbackExecutionId
    ? executions.find((execution) => execution.execution_id === feedbackExecutionId) ?? null
    : null;

  // 이력은 실행과 무관하게 발주계획 전체를 읽는다(목록의 `human_feedback`도 발주계획별 최신 1건이다).
  // 저장 요청의 `expected_revision`은 서버가 (실행, 발주계획)마다 세므로 이 행의 실행에 붙은
  // 수정본에서 계산한다 — 목록의 최신 수정본은 다른 실행의 것일 수 있다.
  const feedbackHistoryQuery = useQuery({
    queryKey: ["order-plan-c2", "feedback-history", selectedItem?.order_plan_pk],
    queryFn: ({ signal }) => api.getOrderPlanScreeningFeedback(
      selectedItem?.order_plan_pk as number,
      null,
      { signal },
    ),
    enabled: dialog === "feedback" && Boolean(selectedItem),
    staleTime: 15_000,
  });

  useEffect(() => {
    const response = listQuery.data;
    if (!response || deepLinkFailed) return;
    const params = new URLSearchParams(searchParams);
    const filtersCleared = reviewPage?.target_filters_cleared === true;
    if (filtersCleared) {
      for (const key of AXIS_KEYS) params.delete(key);
      params.set("qwen", "");
    }
    if (offset > 0) params.set("offset", String(offset));
    else params.delete("offset");
    const addressChanged = params.toString() !== searchParams.toString();
    if (!addressChanged && !isExplicitDeepLink && locateAfterSave === null) return;

    // The already loaded response is the canonical page. Keep it visible when
    // normalizing the URL or releasing the one-shot locate parameter.
    const canonical: OrderPlanListQuery = { ...pageQuery, offset, locate: null };
    if (filtersCleared) {
      Object.assign(canonical, { review_order: "relevance", qwen_relevance: [], stage1_status: [],
        tracking_status: [], feedback_present: undefined, issue: undefined, unjudged: undefined, q: "" });
    }
    if (reviewPage) {
      const resolved = {
        ...response,
        review_page: { ...reviewPage, target_found: null, target_filters_cleared: false },
      };
      queryClient.setQueryData(orderPlanPageKey(canonical), resolved);
      if (addressChanged && pageQuery.locate != null) {
        queryClient.setQueryData(orderPlanPageKey({ ...canonical, locate: pageQuery.locate }), resolved);
      }
    }
    if (addressChanged) {
      setSearchParams(params, { replace: true });
      return;
    }
    if (isExplicitDeepLink) setDeepLinkActive(false);
    if (locateAfterSave !== null) setLocateAfterSave(null);
  }, [deepLinkFailed, isExplicitDeepLink, listQuery.data, locateAfterSave, offset, pageQuery, queryClient, reviewPage, searchParams, setSearchParams]);

  useEffect(() => {
    if (!selectedItem || isExplicitDeepLink || locateAfterSave !== null || !orderPlanSelection.hydrated) return;
    if (selectedPk === selectedItem.order_plan_pk) return;
    const params = new URLSearchParams(searchParams);
    params.set("selected", String(selectedItem.order_plan_pk));
    setSearchParams(params, { replace: true });
    orderPlanSelection.setActiveId(selectedItem.order_plan_pk);
  }, [isExplicitDeepLink, locateAfterSave, orderPlanSelection, searchParams, selectedItem, selectedPk, setSearchParams]);

  useEffect(() => {
    if (!orderPlanSelection.hydrated || !selectedItem || isExplicitDeepLink) return;
    if (orderPlanSelection.activeId !== selectedItem.order_plan_pk) {
      orderPlanSelection.setActiveId(selectedItem.order_plan_pk);
    }
  }, [isExplicitDeepLink, orderPlanSelection, selectedItem]);

  // 결정한 건을 남겨 두는 것은 그 건이 선택돼 있는 동안뿐이다. 다른 건으로 옮기거나 필터를
  // 바꾸면 목록은 다시 필터 그대로다.
  useEffect(() => {
    if (retainedPk !== null && selectedPk !== retainedPk) setRetainedPk(null);
  }, [retainedPk, selectedPk]);
  useEffect(() => {
    setRetainedPk(null);
  }, [selectionFingerprint]);

  // 행이 바뀌면 사람 판단 수정 입력과 선택 사유를 초기화한다. 입력을 잃는 것을 사람이
  // 확인한 뒤에만 여기까지 오도록 이동하는 자리마다 `withRowGuard`를 걸었다.
  useEffect(() => {
    setRelevance(EMPTY_FEEDBACK_DRAFT.relevance);
    setPriority(EMPTY_FEEDBACK_DRAFT.priority);
    setMemo(EMPTY_FEEDBACK_DRAFT.memo);
    setFeedbackBaseline(EMPTY_FEEDBACK_DRAFT);
    setReasonChoice("");
    setCustomReason("");
    setSavedMessage(null);
    setDialog(null);
  }, [selectedItem?.order_plan_pk]);

  function moveSelection(direction: "next" | "previous", afterSave = false): { pk: number; moved: boolean } | null {
    if (!selectedItem) return null;
    const index = visibleItems.findIndex((item) => item.order_plan_pk === selectedItem.order_plan_pk);
    const neighbor = visibleItems[index + (direction === "next" ? 1 : -1)];
    const pk = neighbor?.order_plan_pk ?? (direction === "next" ? reviewPage?.next_pk : reviewPage?.previous_pk);
    if (pk == null) return { pk: selectedItem.order_plan_pk, moved: false };
    const params = new URLSearchParams(searchParams);
    params.set("selected", String(pk));
    if (!neighbor) {
      const nextOffset = offset + (direction === "next" ? PAGE_SIZE : -PAGE_SIZE);
      if (nextOffset > 0) params.set("offset", String(nextOffset));
      else params.delete("offset");
      // Removing the saved row can shift the next row across a page boundary.
      if (afterSave) setLocateAfterSave(pk);
    }
    setSearchParams(params, { replace: true });
    return { pk, moved: true };
  }

  /** 이 행의 실행에 붙은 마지막 수정본 번호. 이력을 읽기 전에는 모른다(`null`). */
  const expectedRevision = feedbackHistoryQuery.data
    ? Math.max(0, ...feedbackHistoryQuery.data.items
      .filter((item) => item.execution_id === feedbackExecutionId)
      .map((item) => item.revision))
    : null;

  const mutation = useMutation({
    mutationFn: () => api.createOrderPlanScreeningFeedback(
      (selectedItem as OrderPlanListItem).order_plan_pk,
      {
        schema_version: "feedback-create-request.v1",
        producer: "human-review-client",
        consumer: "review-api",
        request_id: generateRequestId(),
        execution_id: feedbackExecutionId as string,
        relevance,
        priority: priority || null,
        memo: memo.trim() || null,
        expected_revision: expectedRevision as number,
      },
      actorName,
    ),
    onSuccess: async () => {
      setSavedMessage("사람 판단 수정본을 저장했어요. 추적 상태는 바뀌지 않았어요.");
      // 저장한 값이 새 기준이 된다. 화면의 입력은 그대로 두고 "저장되지 않은 입력"만 푼다.
      setFeedbackBaseline({ relevance, priority, memo });
      await queryClient.invalidateQueries({ queryKey: ["order-plan-c2", "list"] });
      await queryClient.invalidateQueries({ queryKey: ["order-plan-c2", "feedback-history"] });
    },
  });

  const feedbackBlockedReason = !feedbackExecutionId
    ? "이 발주계획에는 판정 결과가 없어 모델 판단에 대한 수정본을 저장할 수 없어요. 판정한 실행 없이 수정본을 만들지 않아요."
    : undefined;
  const ready = !bulkPending && Boolean(selectedItem) && !feedbackBlockedReason && expectedRevision !== null && actorName.trim().length > 0;
  const decisionDisabledReason = feedbackBlockedReason
    ?? (feedbackHistoryQuery.isError
      ? "수정본 이력을 불러오지 못해 저장할 수 없어요."
      : expectedRevision === null
        ? "수정본 이력을 확인한 뒤 저장할 수 있어요."
        : !actorName.trim() ? "담당자 이름을 입력하면 저장할 수 있어요." : undefined);

  // 사람 판단 수정은 저장만 하고 다음 건으로 이동하지 않는다. 이동은 추적 결정이 소유한다.
  function handleSave() {
    if (!ready) return;
    setSavedMessage(null);
    mutation.mutate();
  }

  // --- 추적 결정 (결정 1) ---
  //
  // 사람 판단 수정(`mutation`)과 **다른 mutation·다른 경로**다. ADR-0046 결정 5가 둘을
  // 분리하도록 요구하므로 한 요청으로 합치지 않는다.
  //
  // 소유 사업기회의 기존 PATCH 성공 뒤에만 목록을 다시 읽고 다음 건으로 이동한다.
  const trackingAvailabilityState = trackingAvailability(selectedItem);
  const canStartTracking = selectedItem?.tracking?.tracking_status === "미선택";

  const trackingMutation = useMutation({
    mutationFn: (status: Exclude<OpportunityTrackingStatus, "미선택">) => {
      const tracking = selectedItem?.tracking;
      if (!tracking) throw new Error("추적 결정을 기록할 소유 사업기회가 없어요.");
      return api.updateOpportunityTrackingStatus(
        tracking.opportunity_id,
        status === "계속 추적" && canStartTracking ? { tracking_status: status } : { tracking_status: status, reason: trackingReason },
        trackingActor,
      );
    },
    onError: (error) => {
      if (describeApiError(error, TRACKING_SAVE_FAILED).code === "tracking_start_conflict") {
        void queryClient.invalidateQueries({ queryKey: ["order-plan-c2", "list"] });
      }
    },
    onSuccess: async (saved) => {
      // 방금 저장에 성공한 사유를 비우기 **전에** 잡아 둔다. 이것이 다음 건의
      // `직전 사유 다시 쓰기` 후보이고, 드롭다운을 미리 채우는 것과는 다르다.
      if (saved.tracking_reason) {
        setLastReason(saved.tracking_reason);
        saveSessionValue(LAST_REASON_STORAGE_KEY, saved.tracking_reason);
      }
      // 사유는 건마다 다시 고르는 값이므로 저장에 성공하면 **언제나** 비운다. 다음 건으로
      // 옮겨 가는 경우는 행 전환 effect도 비우지만, 마지막 건은 행이 바뀌지 않아 여기서
      // 비우지 않으면 방금 저장한 사유가 남고 "저장되지 않은 입력"으로도 계속 잡힌다.
      setEditingDecision(null);
      setReasonChoice("");
      setCustomReason("");
      // 영수증은 서버가 돌려준 값만 담는다. 같은 건을 다시 정하면 마지막 결정 하나로 바꾼다.
      if (selectedItem?.tracking && receipts !== null) {
        const receipt: DecidedReceipt = {
          order_plan_pk: selectedItem.order_plan_pk,
          opportunity_id: selectedItem.tracking.opportunity_id,
          title: selectedItem.title,
          agency_name: selectedItem.agency_name,
          budget_amount: selectedItem.budget_amount,
          tracking_status: saved.tracking_status,
          tracking_reason: saved.tracking_reason,
          saved_at: saved.tracking_selected_at,
        };
        const nextReceipts = [receipt, ...receipts.filter((entry) => entry.order_plan_pk !== receipt.order_plan_pk)];
        setReceipts(saveReceipts(nextReceipts) ? nextReceipts : null);
      }
      const next = moveSelection("next", true);
      if (selectedItem && !next?.moved) setRetainedPk(selectedItem.order_plan_pk);
      await queryClient.invalidateQueries({ queryKey: ["order-plan-c2", "list"] });
      // 저장 성공은 화면 알림으로 알린다(C-7, 세 추적 결정 자리가 같은 문장·같은 자리). 시안의 `사업기회에서 보기`·
      // `추적 되돌리기`는 그 사업기회 레코드로 간다 — 되돌리기는 레코드의 기존 되돌리기 확인(사유·담당자 입력)을
      // 열 뿐 여기서 사유를 지어 저장하지 않는다.
      if (next) {
        const opportunityId = selectedItem?.tracking?.opportunity_id ?? saved.id;
        showToast(next.moved
          ? `${trackingSavedMessage(saved.tracking_status)} 다음 발주계획으로 이동해요.`
          : `${trackingSavedMessage(saved.tracking_status)} 현재 목록의 마지막 발주계획이라 이동하지 않아요.`,
        "success",
        [
          { label: "사업기회에서 보기", to: `/opportunities/${opportunityId}/activity` },
          { label: "추적 되돌리기", to: `/opportunities/${opportunityId}/activity?reset=1` },
        ]);
      }
    },
  });

  const trackingAvailabilityReason = bulkPending
    ? "일괄 추적 저장 요청이 끝날 때까지 단건 추적 입력과 저장을 잠가요."
    : trackingAvailabilityState === "contract_missing"
    // 서버 API 계약이 없다는 사실을 실무 결과로 적는다 — 이 화면에서 `계약`은 조달
    // 계약(계약방법)을 가리키는 낱말이라 뜻이 겹친다(0921 명세 §3.1).
    ? "이 발주계획은 추적 결정을 기록하는 기능이 아직 제공되지 않아요."
    : trackingAvailabilityState === "opportunity_missing"
      ? "이 발주계획을 소유한 사업기회를 확인하지 못해 추적 결정을 기록할 수 없어요."
      : undefined;
  const trackingDisabledReason = trackingAvailabilityReason
      // 입력 검증은 세 추적 결정 자리가 같은 순서·같은 문장을 쓴다(C-7).
      ?? trackingInputBlockedReason({
        choice: reasonChoice,
        custom: customReason,
        actorName: trackingActor,
        pending: trackingMutation.isPending,
      }) ?? undefined;
  const trackingReady = !bulkPending && Boolean(selectedItem) && trackingDisabledReason === undefined;
  const startDisabledReason = trackingAvailabilityReason ?? (trackingMutation.isPending
    ? "추적 결정 저장 요청을 처리하고 있어요."
    : trackingActor.trim() ? undefined : "사이드바에서 담당자 이름을 입력해 주세요.");

  function saveTracking(status: Exclude<OpportunityTrackingStatus, "미선택">) {
    setTrackingMessage(null);
    trackingMutation.mutate(status);
  }

  /**
   * 추적 결정은 저장에 성공하면 다음 건으로 이동하므로 사람 판단 수정 입력을 함께
   * 잃는다. `종료`는 되돌릴 수 없어 이미 확인 단계를 거치므로 그 사실을 같은
   * 다이얼로그의 요약에 한 줄로 얹고, 되돌릴 수 있는 두 상태만 이탈 확인을 따로 묻는다.
   */
  function decideTracking(status: Exclude<OpportunityTrackingStatus, "미선택">) {
    if (status === "계속 추적" && canStartTracking ? startDisabledReason !== undefined : !trackingReady) return;
    if (status === "종료") {
      const content = trackingEndConfirmContent({
        actor: trackingActor,
        reason: trackingReason,
        target: `발주계획 ${(selectedItem as OrderPlanListItem).order_plan_unty_no}`,
      });
      setEndConfirm({
        ...content,
        summary: feedbackDirty
          ? [...content.summary, { label: "함께 사라지는 입력", value: "저장하지 않은 사람 판단 수정 입력" }]
          : content.summary,
      });
      return;
    }
    withFeedbackGuard(() => saveTracking(status));
  }

  // 실패 안내도 그 건을 떠나면 사라져야 한다. 다른 건의 결정 바에 남은 오류는 거짓이다.
  useEffect(() => {
    trackingMutation.reset();
    // 열려 있던 확인 단계도 그 건의 것이다. 다른 건으로 옮겨 가면 닫는다.
    setEndConfirm(null);
    setEditingDecision(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedItem?.order_plan_pk]);

  /** 저장하지 않는다. 상태를 미선택에 그대로 두고 다음 건으로만 이동한다(요청안 §4). */
  function skipCurrent() {
    withRowGuard(() => {
      trackingMutation.reset();
      const next = moveSelection("next");
      if (next) {
        setTrackingMessage({
          pk: next.pk,
          text: next.moved
            ? "추적 상태를 바꾸지 않고 다음 발주계획으로 이동했어요. 미선택은 추적 종료가 아니에요."
            : "추적 상태를 바꾸지 않았어요. 현재 목록의 마지막 발주계획이라 이동하지 않아요. 미선택은 추적 종료가 아니에요.",
        });
      }
    });
  }

  /**
   * ↑↓ 목록 이동. 리스너는 목록 `<ul>`이 진다.
   *
   * 경계(현재 페이지의 처음·끝)에서는 hook이 페이지를 모르므로 화면이 맡는다. 두 방향 모두
   * 행이 바뀌는 이동이라 `withRowGuard`를 거치고, 사람이 확인을 취소하면 선택이 그대로여서
   * hook도 초점을 옮기지 않는다.
   */
  const rowNavigation = useRowKeyboardNavigation<number>({
    containerRef: listRef,
    keys: visibleItems.map((item) => item.order_plan_pk),
    onBoundary: (direction) => {
      withRowGuard(() => {
        moveSelection(direction);
      });
    },
    onSelect: selectRow,
    selectedKey: selectedItem?.order_plan_pk ?? null,
  });

  /** 담당자 이름은 감사 표식이다(인증도, 계정도 아니다). 사이드바 담당자 칸과 같은 값으로 저장한다. */
  function changeTrackingActor(value: string) {
    setLocalActor(value);
    setRememberedActorName(value);
  }

  /** Selector의 지우기 단추(`hasClear`)로 선택이 비면 `기타` 자유 입력도 함께 비운다.
   * 비워 둔 채 다른 사유를 고르면 그 값이 그대로 실리므로 별도 처리가 필요 없다. */
  function changeReasonChoice(value: string) {
    setReasonChoice(value);
    if (value === "") setCustomReason("");
  }

  /** 직전 사유를 지금 건에 다시 쓴다. preset에 없는 문장은 `기타`의 자유 입력으로 들어간다. */
  function reuseLastReason() {
    if (!lastReason) return;
    if ((TRACKING_REASONS as readonly string[]).includes(lastReason)) {
      setReasonChoice(lastReason);
      return;
    }
    setReasonChoice(TRACKING_OTHER_REASON);
    setCustomReason(lastReason);
  }

  /**
   * 목록 행에서 Ctrl/Cmd+Enter로 `추적 시작`.
   *
   * 미선택인 건만 이 단축키로 시작한다. 담당자 이름은 사이드바에서 받아 감사에 남긴다.
   */
  function handleRowKeyDown(event: ReactKeyboardEvent<HTMLElement>, pk: number) {
    if (bulkPending) return;
    if (!(event.ctrlKey || event.metaKey) || event.key !== "Enter") return;
    // 초점이 있는 행과 결정이 붙어 있는 건이 다르면(이탈 확인을 취소한 직후) 결정하지 않는다.
    if (pk !== selectedItem?.order_plan_pk || !canStartTracking) return;
    // RecordTable의 Enter→활성 행 변경보다 먼저다. hook의 ↑↓도 defaultPrevented를 보고 비켜난다.
    event.preventDefault();
    if (startDisabledReason === undefined) {
      decideTracking("계속 추적");
      return;
    }
    setTrackingMessage({ pk, text: startDisabledReason });
    if (!trackingActor.trim()) requestActorInput();
  }

  // 오류 문구는 화면마다 따로 만들지 않는다. 서버 raw message를 그대로 싣지
  // 않고 `describeApiError`가 옮긴 문장만 쓴다.
  const listError = describeApiError(listQuery.error, "발주계획 목록을 확인할 수 없어요.").title;
  // 목록 머리글이 "무엇을 보고 있는가"를 문장으로 밝힌다. 축 안은 OR, 축끼리는 AND다.
  // 축 값은 화면 라벨로 조립한다 — URL·서버 값(`relevant`·`filtered_out` …)은 그대로다.
  const filterMeaning = (() => {
    const window = firstObservedFrom ? firstObservedLabel(firstObservedFrom) : null;
    if (isDefaultView) {
      const base = `기본 보기 · ${PRESETS[0].description} · 추적 미선택`;
      return window ? `${base} AND ${window}` : base;
    }
    // 세 단의 탭은 역할을 먼저 말한다(2026-11-18 수정안 3B). 탭 축만 걸린 상태에서만이다.
    const tierPreset = activePreset === "relevant" || activePreset === "uncertain" || activePreset === "unjudged"
      ? PRESETS.find((preset) => preset.key === activePreset)
      : undefined;
    if (tierPreset) {
      const base = tierPreset.axes.tracking.length ? `${tierPreset.description} · 추적 미선택` : tierPreset.description;
      return window ? `${base} AND ${window}` : base;
    }
    const parts: string[] = [];
    if (window) parts.push(window);
    if (stage1Set.size) parts.push(`1차 선별 ${Array.from(stage1Set).map(stage1FilterLabel).join("·")}`);
    if (qwenSet.size) parts.push(`모델 판단 ${Array.from(qwenSet).map(relevanceFilterLabel).join("·")}`);
    if (feedbackSet.size) parts.push(`사람 판단 ${Array.from(feedbackSet).map((token) => (token === "has" ? "있음" : "없음")).join("·")}`);
    if (trackingSet.size) parts.push(`추적 ${Array.from(trackingSet).map((token) => (token === "none" ? ORDER_PLAN_TRACKING_NONE_LABEL : token)).join("·")}`);
    if (issueOn) parts.push("실패·거부만");
    if (unjudgedOn) parts.push("모델 미판정(순위 밖·판정 실패)");
    if (qText.trim()) parts.push(`검색 "${qText.trim()}"`);
    return parts.length ? parts.join(" AND ") : "전체";
  })();

  // 접힌 상세 필터에 걸린 조건 수. 회차·첫 수집 창도 한 축이므로 함께 센다
  // (명세 §2.1, S1) — 접어 두어도 걸려 있다는 사실이 토글 옆 수와 아래 문맥 줄로 드러난다.
  const activeFilterCount = (isDefaultView
    ? 0
    : qwenSet.size + stage1Set.size + feedbackSet.size + trackingSet.size + (issueOn ? 1 : 0) + (unjudgedOn ? 1 : 0) + (qText.trim() ? 1 : 0))
    + (sourceRunId ? 1 : 0)
    + (firstObservedFrom ? 1 : 0);

  // 관련·불확실 탭은 모델 판단을 말한다. 그 보기에서 함께 적용된 추적 조건은 별도로 해제할 수 있다.
  const appliedFilters = ([
    !activePreset && qwenSet.size > 0 && {
      key: "qwen",
      label: `모델 판단 · ${Array.from(qwenSet).map(relevanceFilterLabel).join("·")}`,
      onRemove: () => changeAxes({ qwen: new Set() }),
    },
    stage1Set.size > 0 && {
      key: "stage1",
      label: `1차 선별 · ${Array.from(stage1Set).map(stage1FilterLabel).join("·")}`,
      onRemove: () => changeAxes({ stage1: new Set() }),
    },
    feedbackSet.size > 0 && {
      key: "feedback",
      label: `사람 판단 · ${Array.from(feedbackSet, (value) => value === "has" ? "있음" : "없음").join("·")}`,
      onRemove: () => changeAxes({ feedback: new Set() }),
    },
    trackingSet.size > 0 && {
      key: "tracking",
      label: `추적 선택 · ${Array.from(trackingSet, (value) => value === "none" ? ORDER_PLAN_TRACKING_NONE_LABEL : value).join("·")}`,
      // 암묵적인 기본 보기에서 나가도 모델 판단 축의 범위를 보존한다.
      onRemove: () => changeAxes({ tracking: new Set(), ...(isDefaultView ? { qwen: qwenSet } : {}) }),
    },
    issueOn && {
      key: "issue", label: "선별 처리 · 실패·거부만", onRemove: () => changeAxes({ issue: false }),
    },
    unjudgedOn && activePreset !== "unjudged" && {
      key: "unjudged", label: "모델 미판정", onRemove: () => changeAxes({ unjudged: false }),
    },
    sourceRunId && selectedRunLabel && {
      key: "source_run_id", label: `수집 회차 · ${selectedRunLabel}`, onRemove: () => changeSourceRun(null),
    },
    firstObservedFrom && {
      key: "first_observed_from", label: firstObservedLabel(firstObservedFrom), onRemove: clearFirstObservedFrom,
    },
  ]).filter((filter): filter is AppliedFilter => Boolean(filter));

  const selectedIndex = selectedItem
    ? offset + visibleItems.findIndex((item) => item.order_plan_pk === selectedItem.order_plan_pk) + 1
    : 0;
  /**
   * 패널 헤더 문장(최종 시안 `FinalOrderPlans.dc.html`·`FinalOrderPlansDone.dc.html`). 숫자는 이미 받은
   * 목록에서 센 값(보기 탭 건수·목록 total)만 쓴다. 목록을 읽기 전·실패면 올리지 않아 route 이름이 남는다.
   */
  // 목록 머리 한 줄(시안). 보기 탭이 걸려 있으면 그 탭 이름과 짧은 뜻, 아니면 조합한 필터 설명이다.
  const headPreset = isDefaultView ? PRESETS[0] : PRESETS.find((preset) => preset.key === activePreset);
  const listHeadLabel = headPreset ? headPreset.label : "발주계획";
  // 대시보드 바로가기처럼 첫 수집 창이 더 걸려 있으면 그 조건도 한 줄 안에 밝힌다(걸린 조건을 숨기지 않는다).
  const listHeadScope = headPreset?.key === "relevant" || headPreset?.key === "uncertain"
    ? (firstObservedFrom ? `추적을 정하지 않은 건 · ${firstObservedLabel(firstObservedFrom)}` : "추적을 정하지 않은 건")
    : headPreset?.key === "unjudged"
      ? "모델이 판정하지 않은 건 · 1차 순위순"
      : headPreset?.key === "all"
        ? (firstObservedFrom ? `전체 · ${firstObservedLabel(firstObservedFrom)}` : "전체")
        : filterMeaning;
  const uncertainCount = presetCounts?.uncertain ?? null;
  const relevantDone = listQuery.isSuccess
    && !searchKey(qText)
    && (isDefaultView || activePreset === "relevant")
    && total === 0;
  usePageHeader(relevantDone && uncertainCount !== null && uncertainCount > 0
    ? { description: `불확실로 분류된 ${formatCount(uncertainCount)}건이 남아 있어요.` }
    : null);

  const feedbackSummaryLabel = selectedItem?.human_feedback
    ? `${relevanceLabel(selectedItem.human_feedback.relevance)} · 우선순위 ${priorityLabel(selectedItem.human_feedback.priority)}`
    : "미입력";

  return (
    <section className="c2l-page" data-astryx-theme="bidops" aria-labelledby="order-plans-title">
      {/* 화면의 시각 제목은 상단바의 `<h1>`이 진다(제목 모드, `route-meta.ts`). 페이지가
          같은 이름을 한 번 더 그리면 세로 공간을 두 번 쓰므로 여기에는 문서 구조와
          `aria-labelledby`를 위한 숨긴 제목만 남긴다. */}
      <span className="visually-hidden" id="order-plans-title">발주계획</span>
      {/* 실행 표시와 목록 기준은 **이 화면의 상태**를 쓰므로 셸로 올릴 수 없다. 상단바의
          액션 슬롯으로 보낸다(`PageHeaderActions`). 운영 화면으로 가는 상시 링크
          (`실행 상세 →`)는 없앴다 — 사이드바가 그 동선을 갖고, 문제가 있을 때만 아래
          칩이 그 실행을 특정해 연다(0921 명세 §3.1). */}
      <PageHeaderActions>
        <div className="c2l-header-actions">
          <ExecutionHealthChip
            isError={executionsQuery.isError}
            latest={latestExecutionOverall}
            onRetry={() => { void executionsQuery.refetch(); }}
          />
          {bulkRecoveryAvailable && !bulkDialogMode ? (
            <Button
              label="저장된 일괄 요청 확인"
              size="sm"
              variant="secondary"
              onClick={() => setBulkDialogMode(getPendingOrderPlanBulkTrackingAction() ?? "start")}
            />
          ) : null}
        </div>
      </PageHeaderActions>

      {/* 자동 선별이 꺼져 있으면 사실 한 줄과 운영 화면 링크를 맨 위에 둔다. 활성화된
          판정 기준이 없으면(활성화 전) 배너를 두지 않는다 — 그날은 꺼져 있는 것이 정상이다. */}
      <div className="c2l-notices">
      {dailyTriggerQuery.data ? <DailyTriggerOffBanner state={dailyTriggerQuery.data} /> : null}
      {dailyTriggerQuery.isError ? (
        <Text type="supporting" color="secondary" as="p" className="c2l-daily-trigger-unknown">
          일일 자동 실행 상태를 확인하지 못했어요. 켜져 있다고 가정하지 않아요.
        </Text>
      ) : null}

      {/* 수집 회차 목록 조회 실패는 화면 맨 위 배너가 아니다(시안 M1 승인) — 회차를
          고르지 않은 실무자에게는 업무 장애가 아니므로 선택기 안에서 알리고, 회차가
          걸려 있을 때만 아래 회차 줄에서도 알린다. */}
      {/* 판정이 없는 범위는 원본 발주계획을 그대로 보이고 모델 판단을 값 없음으로 둔다.
          판정 없음을 비관련·실패로 바꾸지 않는다. */}
      {listQuery.isSuccess && listScope === null ? (
        <Banner status="info" title="선별 전 · 수집 데이터 조회"
          description="이 회차에 게시된 선별 결과가 없어요. 원본 발주계획을 조회하며 모델 판단은 값 없음으로 표시해요." collapsible={false} />
      ) : null}
      {/* 판정이 없다는 사실과 그것이 비관련이 아니라는 뜻은 남기고, 실행 식별자 나열은
          운영 화면으로 보냈다(0921 명세 §3.1). 실패·중단·중지를 성공으로 읽지 않는다는
          경고 문장은 그대로다(경고 ④). */}
      {listQuery.isSuccess && listScope?.mode === "cumulative" && listScope.policy_versions.length === 0 ? (
        <Banner status="info" title="누적 판정 없음 · 수집 데이터 조회"
          description="운영 선별 판정이 아직 없어요. 수집된 발주계획을 조회하며 모델 판단은 값 없음으로 표시해요. 실패·중단·중지 상태를 성공 결과로 해석하지 않아요."
          collapsible={false} />
      ) : null}

      {isExplicitDeepLink && invalidSelectedParam ? (
        <Banner status="error" title="발주계획 식별자가 올바르지 않아요"
          description="요청한 발주계획을 선택하지 못했어요. 목록의 행을 직접 선택해 주세요." collapsible={false} />
      ) : null}
      </div>
      <PageHeaderTabs>
        {/* 탐색과 추적 4화면이 같은 필터 골격을 쓴다(`WorkspaceFilters`). 보기 탭과
            검색만 늘 보이고, 기술 축은 `상세 필터` 뒤에 접어 둔다. 접어도 URL 동기화와
            축의 AND/OR 의미는 그대로이며, 접힌 채로 걸려 있는 필터 수를 토글이 말한다. */}
        <WorkspaceFilterBar
          activeFilterCount={activeFilterCount}
          aria-label="C-2 결과 필터"
          className="c2l-filters"
        >
          <WorkspaceFilterLine>
            {/* 보기별 건수는 서버가 범위 전체를 기준으로 함께 반환한다. */}
            <WorkspaceViewTabs
              label="보기"
              onChange={applyPreset}
              tabs={PRESETS.map((preset) => ({
                key: preset.key,
                label: preset.label,
                count: presetCounts?.[preset.key] ?? null,
              }))}
              value={activePreset ?? ""}
            />
          </WorkspaceFilterLine>

          <WorkspaceFilterTools className="c2l-filter-tools">
            <AppliedFilterTokens filters={appliedFilters} isDisabled={bulkPending} />
            <WorkspaceAdvancedToggle
              activeCount={activeFilterCount}
              controlsId="c2l-advanced-filters"
              isOpen={advancedOpen}
              onToggle={() => setAdvancedOpen((open) => !open)}
              visibleLabel="필터"
            />
            <WorkspaceSearch
              appliedValue={qText}
              isDisabled={bulkPending}
              label="사업명·발주기관·계획번호 검색"
              onChange={setSearchText}
              onClear={() => applySearch("")}
              onEnter={() => applySearch(searchText)}
              placeholder="사업명·발주기관·계획번호 검색"
              value={searchText}
            />
          </WorkspaceFilterTools>

          <WorkspaceFilterAdvanced
            isOpen={advancedOpen}
            onClose={() => setAdvancedOpen(false)}
            id="c2l-advanced-filters"
            onReset={resetFilters}
            resetLabel="기본값으로"
          >
            <WorkspaceFilterGroup title="조회 범위">
              <SourceRunFilter
                allRunsDescription="활성화된 적 있는 policy의 운영 판정 누적"
                extraRunIds={runOptionSourceIds}
                isDisabled={bulkPending}
                isError={runsQuery.isError}
                isPending={runsQuery.isPending}
                onChange={changeSourceRun}
                onRetry={() => { void runsQuery.refetch(); }}
                runs={collectionRuns}
                value={sourceRunId}
              />
              <Selector
                label="저장된 뷰"
                size="sm"
                options={savedViews.map((view) => ({ value: view.id, label: view.name }))}
                value=""
                onChange={(id) => {
                  const view = savedViews.find((item) => item.id === id);
                  if (view) applySavedViewSearch(view.search);
                }}
                placeholder={savedViews.length ? "저장된 뷰 선택" : "저장된 뷰 없음"}
                isDisabled={savedViews.length === 0}
              />
              <div className="c2l-saved-views-row">
                {isNamingView ? (
                  <>
                    <ReviewFilterTextInput label="뷰 이름" value={newViewName} onChange={setNewViewName} placeholder="뷰 이름" onEnter={saveCurrentAsView} />
                    <Button label="뷰 저장" size="sm" onClick={saveCurrentAsView} isDisabled={!newViewName.trim()} />
                    <Button label="취소" size="sm" variant="ghost" onClick={() => { setIsNamingView(false); setNewViewName(""); }} />
                  </>
                ) : (
                  <Button label="현재 필터를 뷰로 저장" size="sm" variant="ghost" onClick={() => setIsNamingView(true)} />
                )}
              </div>
              {savedViews.length ? (
                <ul className="c2l-saved-view-list">
                  {savedViews.map((view) => (
                    <li key={view.id}>
                      <Text type="supporting" color="secondary" as="span">{view.name}</Text>
                      <Button label={`${view.name} 삭제`} isIconOnly icon={<span aria-hidden="true">×</span>} size="sm" variant="ghost" onClick={() => deleteSavedView(view.id)} />
                    </li>
                  ))}
                </ul>
              ) : null}
            </WorkspaceFilterGroup>
            <WorkspaceFilterGroup title="모델 선별">
              <MultiSelector
                label="모델 판단"
                size="sm"
                placeholder="전체"
                formatValue={formatFilterValues}
                options={RELEVANCE_TOKENS.map((value) => ({ value, label: relevanceFilterLabel(value) }))}
                value={Array.from(qwenSet)}
                onChange={(value) => changeAxes({ qwen: new Set(value as RelevanceToken[]) })}
              />
              <MultiSelector
                label="1차 선별"
                size="sm"
                placeholder="전체"
                formatValue={formatFilterValues}
                options={STAGE1_TOKENS.map((value) => ({ value, label: stage1FilterLabel(value) }))}
                value={Array.from(stage1Set)}
                onChange={(value) => changeAxes({ stage1: new Set(value as Stage1Token[]) })}
              />
              {/* 1차 선별과 모델 판정 양쪽의 실패·거부를 포함한다. */}
              <Selector
                label="선별 처리 상태"
                size="sm"
                options={[{ value: "all", label: "전체" }, { value: "issue", label: "실패·거부만" }]}
                value={issueOn ? "issue" : "all"}
                onChange={(value) => changeAxes({ issue: value === "issue" })}
              />
            </WorkspaceFilterGroup>
            <WorkspaceFilterGroup title="사람 판단·추적">
              <MultiSelector
                label="사람 판단"
                size="sm"
                placeholder="전체"
                formatValue={formatFilterValues}
                options={[{ value: "has", label: "있음" }, { value: "none", label: "없음" }]}
                value={Array.from(feedbackSet)}
                onChange={(value) => changeAxes({ feedback: new Set(value as FeedbackToken[]) })}
              />
              <MultiSelector
                label="추적 선택"
                size="sm"
                placeholder="전체"
                formatValue={formatFilterValues}
                options={TRACKING_TOKENS.map((value) => ({ value, label: value === "none" ? ORDER_PLAN_TRACKING_NONE_LABEL : value }))}
                value={Array.from(trackingSet)}
                onChange={(value) => changeAxes({ tracking: new Set(value as TrackingToken[]) })}
              />
            </WorkspaceFilterGroup>
          </WorkspaceFilterAdvanced>

          {/* 회차 줄 — 상세 필터를 접었는지와 무관하게 그린다(명세 §2.1). 측정 전용
              실행 표식이 여기 하나로 모인다(시안 M1 승인 A안): 지금 보는 목록이 운영
              판정이 아니라는 사실을 알리는 자리이므로 어느 경로에서도 사라지면 안 된다. */}
          {sourceRunId && selectedRunLabel ? (
            <WorkspaceFilterContext className="c2l-filter-context">
              <SourceRunContextLine
                badge={listScope?.mode === "run" && listScope.purpose === "gate_measurement"
                  ? <StatusMark mark={{ label: "측정 전용 실행", tone: "warning" }} />
                  : null}
                label={selectedRunLabel}
                onClearRun={() => changeSourceRun(null)}
                reason={runsQuery.isError ? "회차 목록 조회 실패" : null}
              />
            </WorkspaceFilterContext>
          ) : null}

          {/* 첫 수집 창 줄 — 회차 줄과 같은 자리·같은 방식이다(S1). 대시보드 `새 관련
              발주계획`이 이 인자로 화면을 열므로, 창이 조용히 목록을 좁히지 않게
              접힘과 무관하게 그린다. */}
          {firstObservedFrom ? (
            <WorkspaceFilterContext className="c2l-filter-context">
              <div className="c2l-observed-context">
                <Text type="label" color="primary" as="span">{firstObservedLabel(firstObservedFrom)}</Text>
                <Button label="해제" onClick={clearFirstObservedFrom} size="sm" variant="ghost" />
              </div>
            </WorkspaceFilterContext>
          ) : null}
        </WorkspaceFilterBar>
      </PageHeaderTabs>
      <WorkspaceFrame>
        {/* 관련 보기를 다 정한 날(최종 시안 `FinalOrderPlansDone`): 두 pane 대신 다 했다는 사실과 다음 길을
            준다. 불확실 건이 남아 있으면 그 탭이 먼저다 — 관련이 0건이라고 검토가 끝난 것이 아니다.
            시안의 `오늘 정한 발주계획` 목록·`추적 되돌리기` 토스트는 그 날의 결정 목록·되돌리기 API가 없어
            그리지 않는다. */}
        {relevantDone ? (
          <section aria-labelledby="c2l-done-title" className="c2l-done" data-testid="order-plan-relevant-done">
            <span aria-hidden="true" className="c2l-done-mark">
              <svg fill="none" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.4} viewBox="0 0 24 24"><path d="m5 12 5 5 9-10" /></svg>
            </span>
            <div className="c2l-done-text">
              <h2 id="c2l-done-title">추적을 정하지 않은 관련 건이 없어요</h2>
              <p>
                {(uncertainCount ?? 0) > 0
                  ? `불확실 ${formatCount(uncertainCount ?? 0)}건이 남아 있어요. 관련이 0건이라고 검토가 끝난 것은 아니에요.`
                  : "다른 보기에서 남은 발주계획을 볼 수 있어요."}
              </p>
            </div>
            <div className="c2l-done-actions">
              {(uncertainCount ?? 0) > 0 ? (
                <button className="c2l-done-primary" onClick={() => applyPreset("uncertain")} type="button">
                  불확실 {formatCount(uncertainCount ?? 0)}건 검토하기
                </button>
              ) : (
                <button className="c2l-done-primary" onClick={viewEndedTracking} type="button">종료한 건 보기</button>
              )}
              <button className="panel-header-link" onClick={() => applyPreset("all")} type="button">전체 발주계획 보기</button>
            </div>
          </section>
        ) : null}
        {relevantDone && receipts !== null && receipts.length > 0 ? (
          <section aria-labelledby="c2l-receipts-title" className="c2l-receipts" data-testid="order-plan-tab-receipts">
            <div className="c2l-receipts-head">
              <h2 id="c2l-receipts-title">이 탭에서 정한 발주계획</h2>
              <span className="c2l-receipts-count">{formatCount(receipts.length)}건</span>
            </div>
            <p className="c2l-receipts-note">이 브라우저 탭에서 저장에 성공한 결정만 모았어요. 서버 기록은 사업기회 화면이 정본이에요.</p>
            <ul className="c2l-receipt-list">
              {receipts.map((receipt) => (
                <li className="c2l-receipt" key={receipt.order_plan_pk}>
                  <div className="c2l-receipt-main">
                    <Link className="c2l-receipt-title" to={`/opportunities/${receipt.opportunity_id}/activity`}>{textOrUnknown(receipt.title)}</Link>
                    <span className="c2l-receipt-sub">
                      {[textOrUnknown(receipt.agency_name), receipt.budget_amount === null ? "예산 미제공" : formatCompactPrice(receipt.budget_amount), receipt.tracking_reason ? `사유: ${receipt.tracking_reason}` : null].filter(Boolean).join(" · ")}
                    </span>
                  </div>
                  <StatusMark mark={{
                    label: receipt.tracking_status === "계속 추적" ? "추적 중" : receipt.tracking_status === "종료" ? "추적 종료" : receipt.tracking_status,
                    tone: receipt.tracking_status === "계속 추적" ? "accent" : "neutral",
                  }} />
                  <Link className="panel-header-link" to={`/opportunities/${receipt.opportunity_id}/activity?reset=1`}>추적 되돌리기</Link>
                </li>
              ))}
            </ul>
          </section>
        ) : null}

        {/* 목록을 불러오는 중이거나 실패해도 두 pane 골격은 그대로 둔다. 화면이 통째로
            접혔다 펴지면 사람이 보던 자리를 잃는다(시안의 loading·failure 상태). */}
        {relevantDone ? null : <SplitWorkspace
            aria-label="발주계획 목록과 상세"
            className="c2l-workspace"
          >
            <aside className="review-split-list c2l-list-pane">
              <header className="review-list-head c2l-list-head">
                <p className="c2l-list-heading" title={filterMeaning}>
                  <span className="c2l-list-count">
                    {listHeadLabel} {listQuery.isError
                      ? "건수 확인 불가"
                      : listQuery.isPending
                        ? "불러오는 중"
                        : `${formatCount(total)}건`}
                  </span>
                  <span className="c2l-list-scope"> · {listHeadScope}</span>
                </p>
              </header>
              {/* A4: 일괄 종료 직후 안내. N=0이면 표시하지 않고, 다음 필터·선택 변경까지
                  남는다(`applyAxes`·`toggleChecked`·`선택 전체 해제`가 지운다). */}
              {bulkEndNotice !== null ? (
                <p className="c2l-bulk-end-notice" role="status">
                  {bulkEndNotice.toLocaleString("ko-KR")}건을 추적 종료했어요 · 추적 필터 &apos;종료&apos;에서 볼 수 있어요
                </p>
              ) : null}
              <SelectionToolbar
                className="c2l-selection-toolbar"
                count={orderPlanSelection.selectedIds.length}
                data-testid="order-plan-selection-toolbar"
                label="발주계획 선택 작업"
                reasonId="c2l-selection-action-reason"
                reason={bulkPending
                  ? "일괄 추적 요청을 처리하는 동안 선택을 바꿀 수 없어요."
                  : mutation.isPending || trackingMutation.isPending
                    ? "기존 저장 요청이 끝날 때까지 일괄 추적을 시작할 수 없어요."
                  : !orderPlanSelection.hydrated
                    ? "목록 선택 상태를 준비하는 중이에요."
                    : !orderPlanSelection.storageAvailable || orderPlanSelection.storageError
                      ? "선택 저장소를 확인하지 못해 단건 추적 경로를 사용해 주세요."
                      : orderPlanSelection.selectedIds.length > ORDER_PLAN_BULK_END_MAX_SELECTION
                          ? "한 번에 200건까지 종료할 수 있어요. 선택을 줄여 주세요."
                          : ""}
                selectPage={{
                  onClick: selectCurrentPage,
                  disabled: bulkPending || !orderPlanSelection.hydrated || !orderPlanSelection.storageAvailable || visibleItems.length === 0 || pageFullySelected,
                }}
                clearSelection={{
                  onClick: () => {
                    orderPlanSelection.clear();
                    setBulkEndNotice(null);
                  },
                  disabled: bulkPending || orderPlanSelection.selectedIds.length === 0 || !orderPlanSelection.hydrated,
                }}
                startTracking={{
                  onClick: () => setBulkDialogMode("start"),
                  disabled: bulkPending || mutation.isPending || trackingMutation.isPending || !orderPlanSelection.hydrated || !orderPlanSelection.storageAvailable || Boolean(orderPlanSelection.storageError) || orderPlanSelection.selectedIds.length === 0,
                }}
                actions={(
                    <Button
                      aria-describedby="c2l-selection-action-reason"
                      isDisabled={bulkPending || mutation.isPending || trackingMutation.isPending || !orderPlanSelection.hydrated || !orderPlanSelection.storageAvailable || Boolean(orderPlanSelection.storageError) || orderPlanSelection.selectedIds.length === 0 || orderPlanSelection.selectedIds.length > ORDER_PLAN_BULK_END_MAX_SELECTION}
                      aria-label="선택한 계획 추적 종료"
                      label="추적 종료"
                      onClick={() => setBulkDialogMode("end")}
                      size="sm"
                      variant="secondary"
                    />
                )}
              />
              {(!orderPlanSelection.storageAvailable || orderPlanSelection.storageError) && orderPlanSelection.hydrated ? (
                <p className="c2l-selection-storage-warning" role="alert">
                  이 탭의 선택 저장소를 사용할 수 없어 일괄 추적을 사용할 수 없어요. 단건 추적 경로를 사용해 주세요.
                </p>
              ) : null}

              <RecordTable
                activeKey={selectedItem?.order_plan_pk ?? null}
                className="c2l-list-scroll"
                columns={orderPlanColumns({
                  unjudged: unjudgedOn,
                  hideModelLabel: activePreset === "relevant" || activePreset === "uncertain" ? activePreset : null,
                  hideUntracked: activePreset === "relevant" || activePreset === "uncertain",
                })}
                getKey={(item) => item.order_plan_pk}
                getRowLabel={(item) => textOrUnknown(item.title)}
                isRowDisabled={() => bulkPending}
                label="발주계획 검토 목록"
                navigation={rowNavigation}
                onActivate={selectRow}
                onRowKeyDown={(event, item) => handleRowKeyDown(event, item.order_plan_pk)}
                rowClassName="c2l-row"
                rows={visibleItems}
                selection={{
                  getChecked: (item) => orderPlanSelection.selectedIdSet.has(item.order_plan_pk),
                  getLabel: (item) => `${textOrUnknown(item.title)} 선택`,
                  onCheckedChange: (item, checked) => toggleChecked(item.order_plan_pk, checked),
                }}
                state={listQuery.isPending ? {
                  kind: "loading", label: "발주계획을 불러오는 중…", lines: 3, showLabel: true,
                } : listQuery.isError ? {
                  kind: "error",
                  message: {
                    title: "발주계획 목록을 불러오지 못했어요",
                    description: listError,
                    action: { label: "다시 시도", onClick: () => { void listQuery.refetch(); } },
                  },
                } : visibleItems.length === 0 ? {
                  kind: "empty",
                  message: {
                    title: "조건에 맞는 계획이 없어요",
                    description: searchKey(qText)
                      ? `적용된 검색어 "${qText}"와 다른 활성 필터에 맞는 계획이 없어요.`
                      : "필터를 바꿔보세요. 표시되지 않은 값이나 판정 실패를 다른 모델 판단으로 바꾸지 않아요.",
                    action: searchKey(qText)
                      ? { label: "검색어만 지우기", onClick: () => applySearch("") }
                      : { label: "필터 초기화", onClick: resetFilters },
                  },
                } : undefined}
                viewportRef={listRef}
              />
              {/* 바닥 안내 줄 — 실무자가 알아야 할 **경고가 있을 때만** 보인다(2026-09-21
                  사용자 결정). 평상시(누적 · 활성 policy 판정 있음)에는 그리지 않는다.
                  - 정렬 설명은 지웠다: 행마다 관련도 표식이 있어 순서가 자명하다.
                  - 기본 보기 숨김 안내는 지웠다: `전체` 탭과 그 건수가 "더 있다"를 이미 구조로
                    보여 주고, 문구가 `BM25 선정 제외` 같은 파이프라인 용어라 읽고 행동할 수 없다.
                  - 회차 모드도 더는 여기 적지 않는다(시안 M1 승인 A안). 회차와 ` · 측정 전용
                    실행` 표식은 필터 둘째 줄의 회차 줄 하나로 모았다 — 같은 경고를 두 곳에
                    두지 않되, 표식 자체는 접힘과 무관하게 늘 보인다.
                  - 남는 것은 `판정 없음` 계열뿐이다: ① 판정 없음(`null`) ② 누적인데 활성화된
                    적 있는 policy 판정이 없음. 범위를 모르면(`undefined`) 적지 않는다. */}
              {listScope === null
                || (listScope?.mode === "cumulative" && listScope.policy_versions.length === 0) ? (
                <div className="c2l-list-foot">
                  <p className="c2l-list-scope" data-testid="order-plan-list-scope" title={scopeLabel(listScope)}>
                    <Text type="supporting" color="secondary" as="span">{scopeLabel(listScope)}</Text>
                  </p>
                </div>
              ) : null}
              {/* 페이저 줄은 안내 아래 마지막 줄이다. 네 화면이 같은 공용 부품을 쓴다. */}
              {listQuery.isPending || listQuery.isError ? null : (
                <ListPagerControls
                  className="c2l-pager"
                  keyboardAction="추적 시작"
                  label="발주계획 목록 페이지"
                  offset={offset}
                  onNext={() => changeOffset(offset + PAGE_SIZE)}
                  onPrevious={() => changeOffset(Math.max(0, offset - PAGE_SIZE))}
                  total={total}
                  visibleCount={visibleItems.length}
                />
              )}
            </aside>

            <OrderPlanDetailPane
              listPending={listQuery.isPending}
              listError={listQuery.isError}
              isExplicitDeepLink={isExplicitDeepLink}
              deepLinkFailed={deepLinkFailed}
              invalidSelectedParam={invalidSelectedParam}
              isCumulative={isCumulative}
              explicitTargetInFilteredItems={explicitTargetInFilteredItems}
              selectedItem={selectedItem}
              trackingAvailabilityState={trackingAvailabilityState}
              selectedSourceUrl={selectedSourceUrl}
              feedbackSummaryLabel={feedbackSummaryLabel}
              rowExecution={rowExecution}
              bulkPending={bulkPending}
              onOpenFeedback={() => setDialog("feedback")}
              trackingProblem={trackingMutation.isError ? describeApiError(trackingMutation.error, TRACKING_SAVE_FAILED) : null}
              trackingMessage={trackingMessage}
              trackingDisabledReason={trackingDisabledReason}
              startDisabledReason={startDisabledReason}
              trackingActor={trackingActor}
              onActorNameChange={changeTrackingActor}
              customReason={customReason}
              onCustomReasonChange={setCustomReason}
              reasonChoice={reasonChoice}
              onReasonChoiceChange={changeReasonChoice}
              lastReason={lastReason}
              onReuseLastReason={reuseLastReason}
              selectedIndex={selectedIndex}
              total={total}
              trackingSectionRef={trackingSectionRef}
              editingDecision={editingDecision}
              decisionLocked={Boolean(trackingAvailabilityReason) || trackingMutation.isPending}
              onEditDecision={(status) => {
                setEditingDecision(status);
                if (!status) changeReasonChoice("");
              }}
              trackingReady={trackingReady}
              onDecideTracking={decideTracking}
              onSkipCurrent={skipCurrent}
              onResetFilters={resetFilters}
            />
        </SplitWorkspace>}
      </WorkspaceFrame>

      {/* 사람 판단 수정. 추적 결정과 다른 요청·다른 저장이며 다음 건으로 이동하지 않는다. */}
      <Dialog isOpen={dialog === "feedback" && selectedItem !== null} onOpenChange={(open) => { if (!open) setDialog(null); }} purpose="form" width={560}>
        <DialogHeader
          title="사람 판단 수정 (선택)"
          subtitle={selectedItem ? textOrUnknown(selectedItem.title) : undefined}
          onOpenChange={() => setDialog(null)}
        />
        <div className="c2l-dialog-body c2l-feedback-dialog">
          <Text type="supporting" color="secondary" as="p">
            기존 사람 판단을 그대로 둬요. 추적 결정과는 별도 수정본이며 적합성 등급·참여 준비 상태·심층 추적 승인·최종 Go/No-Go를 채우거나 대신하지 않아요.
          </Text>
          <StatusMark mark={{ label: selectedItem?.human_feedback ? feedbackSummaryLabel : "사람 판단 미입력", tone: "neutral" }} />
          {/* 수정본이 붙는 판정의 실행 식별자·policy는 운영 화면이 진다(0921 명세 §3.1).
              저장 요청은 그대로 그 행의 실행에 묶인다. 판정이 없으면 입력을 막고 이유를 말한다. */}
          {feedbackExecutionId ? null : (
            <Text type="supporting" color="secondary" as="p" className="c2l-feedback-target" role="note">{feedbackBlockedReason}</Text>
          )}

          {feedbackHistoryQuery.isPending ? (
              <Text type="supporting" color="secondary" as="p" role="status">사람 판단 수정 이력을 불러오는 중…</Text>
            ) : feedbackHistoryQuery.isError ? (
              <Text type="supporting" color="secondary" as="p" role="alert">사람 판단 수정 이력을 불러오지 못했어요. 저장 전 현재 수정본을 확인할 수 없어요.</Text>
            ) : (
              <ReviewRevisionHistory
                className="c2l-feedback-history"
                empty="사람 판단 수정이 없어요. 사람 판단을 새 수정본으로 기록할 수 있어요."
                entries={(feedbackHistoryQuery.data?.items ?? []).map((item) => ({
                  actor: item.claimed_name,
                  at: formatMoment(item.created_at),
                  body: (
                    <dl>
                      <div><dt>우선순위</dt><dd>{priorityLabel(item.priority)}</dd></div>
                      <div><dt>메모</dt><dd>{item.memo ?? "메모 미제공"}</dd></div>
                    </dl>
                  ),
                  id: item.feedback_id,
                  revision: item.revision,
                  tags: <StatusMark mark={{ label: relevanceLabel(item.relevance), tone: "neutral" }} />,
                }))}
                headingLevel={5}
                label="사람 판단 수정 이력"
              />
            )}

          {/* 라벨과 선택지는 한글이고 **저장 요청에 실리는 값(`value`)은 그대로**다. */}
          <div className="c2l-feedback-field">
            <Text type="label" color="secondary" as="p">관련성</Text>
            <SegmentedControl isDisabled={bulkPending || Boolean(feedbackBlockedReason)} value={relevance} onChange={(value) => setRelevance(value as OrderPlanRelevance)} label="사람 판단 관련성">
              <SegmentedControlItem value="relevant" label="관련" />
              <SegmentedControlItem value="uncertain" label={ORDER_PLAN_FEEDBACK_RELEVANCE_LABEL.uncertain} />
              <SegmentedControlItem value="not_relevant" label="비관련" />
            </SegmentedControl>
          </div>

          <div className="c2l-feedback-field">
            <Text type="label" color="secondary" as="p">우선순위</Text>
            <SegmentedControl isDisabled={bulkPending || Boolean(feedbackBlockedReason)} value={priority || "null"} onChange={(value) => setPriority(value === "null" ? "" : (value as OrderPlanFeedbackPriority))} label="사람 판단 우선순위">
              <SegmentedControlItem value="high" label="높음" />
              <SegmentedControlItem value="medium" label="보통" />
              <SegmentedControlItem value="low" label="낮음" />
              <SegmentedControlItem value="null" label="미지정" />
            </SegmentedControl>
          </div>

          <TextArea
            label="메모"
            value={memo}
            onChange={setMemo}
            rows={3}
            placeholder="사람 검토 근거 또는 다음 확인 사항"
            isDisabled={bulkPending || Boolean(feedbackBlockedReason)}
          />

          <TextInput
            label="사람 판단 담당자 이름"
            value={actorName}
            onChange={setActorName}
            description="감사 귀속용 이름이며 로그인·신원 인증·권한 부여가 아니에요."
            isDisabled={bulkPending || Boolean(feedbackBlockedReason)}
          />

          <div className="c2l-feedback-actions">
            {mutation.isError ? <Text type="body" color="secondary" role="alert">{describeApiError(mutation.error, "사람 판단 수정을 저장하지 못했어요.").title}</Text> : null}
            {savedMessage ? <Text type="body" color="secondary" role="status">{savedMessage}</Text> : null}
            <ReviewDecisionAction
              disabledReason={decisionDisabledReason}
              isDisabled={!(ready && !mutation.isPending)}
              label="새 수정본 저장"
              variant="secondary"
              onClick={handleSave}
            />
          </div>
        </div>
      </Dialog>

      {/* 되돌릴 수 없는 `종료`의 확인 단계. 취소하면 초안은 그대로 남고 요청은 나가지
          않으며, 저장에 실패하면 다이얼로그는 닫히고 결정 바의 오류 문구가 남는다.
          확인 문구는 사전규격·사업 추적과 같은 `trackingEndConfirmContent`에서 온다. */}
      <ConfirmDecisionDialog
        confirmLabel={endConfirm?.confirmLabel ?? "종료 상태로 저장"}
        isPending={trackingMutation.isPending}
        onConfirm={() => {
          setTrackingMessage(null);
          trackingMutation.mutate("종료", { onSettled: () => setEndConfirm(null) });
        }}
        onOpenChange={(next) => { if (!next) setEndConfirm(null); }}
        open={endConfirm !== null}
        summary={endConfirm?.summary ?? []}
        title={endConfirm?.title ?? "추적을 종료해요"}
      />
      <OrderPlanBulkTrackingDialog
        open={bulkDialogMode !== null}
        mode={bulkDialogMode ?? "start"}
        selectedIds={orderPlanSelection.selectedIds}
        selectionGeneration={orderPlanSelection.state.selectionGeneration}
        filterFingerprint={selectionFingerprint}
        actorName={trackingActor}
        onClose={() => {
          setBulkDialogMode(null);
          setBulkRecoveryAvailable(hasPendingOrderPlanBulkTrackingRequest());
        }}
        onApplied={(resolvedIds, generation, summary) => {
          orderPlanSelection.applyResult(resolvedIds, generation);
          // A4: 종료가 실제로 성공한 건이 있을 때만 안내를 켠다. 0이면 표시하지 않는다.
          if (bulkDialogMode === "end" && summary.succeeded_plan_count > 0) {
            setBulkEndNotice(summary.succeeded_plan_count);
          }
        }}
        onInvalidate={invalidateBulkQueries}
        onPersistSelection={orderPlanSelection.persist}
        onPendingChange={handleBulkPendingChange}
        storageAvailable={orderPlanSelection.storageAvailable}
        storageError={orderPlanSelection.storageError?.message ?? null}
      />
      {toast ? <Toast links={toast.links} message={toast.message} onDismiss={dismissToast} variant={toast.variant} /> : null}
    </section>
  );
}
