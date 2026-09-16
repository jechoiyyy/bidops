import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { KeyboardEvent as ReactKeyboardEvent, Ref } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router-dom";
import { Badge } from "@astryxdesign/core/Badge";
import { Banner } from "@astryxdesign/core/Banner";
import { Button } from "@astryxdesign/core/Button";
import { Dialog, DialogHeader } from "@astryxdesign/core/Dialog";
import { Heading } from "@astryxdesign/core/Heading";
import { SegmentedControl, SegmentedControlItem } from "@astryxdesign/core/SegmentedControl";
import { Selector } from "@astryxdesign/core/Selector";
import { Stack } from "@astryxdesign/core/Stack";
import { Tab, TabList } from "@astryxdesign/core/TabList";
import { TextArea } from "@astryxdesign/core/TextArea";
import { TextInput } from "@astryxdesign/core/TextInput";
import { ToggleButton, ToggleButtonGroup } from "@astryxdesign/core/ToggleButton";
import { Text } from "@astryxdesign/core/Text";
import { ConfirmDecisionDialog, trackingEndConfirmContent } from "../components/common/ConfirmDecisionDialog";
import { PageHeaderActions } from "../components/common/PageHeaderActions";
import { useRowKeyboardNavigation } from "../components/common/useRowKeyboardNavigation";
import type { RowKeyboardNavigationRowProps } from "../components/common/useRowKeyboardNavigation";
import { useUnsavedGuard } from "../components/common/useUnsavedGuard";
import { useListSelection } from "../components/common/useListSelection";
import {
  DenseList,
  DenseListRow,
  ReviewDecisionAction,
  ReviewDecisionBar,
  ReviewFilterSelector,
  ReviewFilterTextInput,
  ReviewRevisionHistory,
  ReviewState,
  ReviewStatus,
  ReviewValue,
  SplitWorkspace,
  StickyDecisionHeader,
} from "../components/common/ReviewPrimitives";
import {
  WorkspaceAdvancedToggle,
  WorkspaceFilterAdvanced,
  WorkspaceFilterBar,
  WorkspaceFilterEnd,
  WorkspaceFilterLine,
  WorkspaceFrame,
  WorkspaceSearch,
  WorkspaceViewTabs,
} from "../components/common/WorkspaceFilters";
import { api } from "../lib/api";
import { describeApiError } from "../lib/apiErrors";
import { formatCompactPrice } from "../lib/deadline";
import { generateRequestId } from "../lib/requestId";
import {
  ORDER_PLANS_SELECTION_STORAGE_KEY,
  orderPlansFilterFingerprint,
} from "../lib/listSelection";
import {
  hasPendingOrderPlanBulkTrackingRequest,
  OrderPlanBulkTrackingDialog,
} from "../components/order-plans/OrderPlanBulkTrackingDialog";
import type {
  OrderPlanFeedbackPriority,
  OrderPlanListItem,
  OrderPlanListResponse,
  OrderPlanRelevance,
  OrderPlanScreeningExecutionDetailResponse,
  OrderPlanScreeningExecutionListResponse,
  OrderPlanScreeningExecutionSummary,
  OrderPlanStage1Status,
  OrderPlanStage2Status,
  OpportunityTrackingStatus,
} from "../lib/types";
import "../styles/order-plans.css";

const PAGE_SIZE = 500;
const MIN_LIST_WIDTH = 300;
const MAX_LIST_WIDTH = 640;
/**
 * 시안의 목록 폭은 작업 영역의 **38%**다(IMPLEMENTATION-CONTRACT §고정할 기준).
 * 고정 px 로 비율을 근사하지 않는다 — 폭이 바뀌면 근사값은 어긋나고, 같은 셸을 쓰는
 * 다른 화면과 기본값이 달라진다. 사람이 손으로 끌면 그때부터 px 로 고정된다.
 */
const DEFAULT_LIST_WIDTH = "38%";
const LIST_WIDTH_STEP = 24;
const LIST_WIDTH_STORAGE_KEY = "bidops.order-plans.listWidth";
const SAVED_VIEWS_STORAGE_KEY = "bidops.order-plans.views";

/**
 * 마우스 좌표는 화면에 그려진 좌표이고 목록 폭은 CSS layout px 이다.
 * offsetWidth와 bounding rect는 모두 목록 테두리를 포함하므로, 두 값을 나누면
 * 브라우저가 계산한 실제 렌더링 배율을 선언값 없이 얻을 수 있다.
 */
function renderedHorizontalScale(element: HTMLElement): number {
  const layoutWidth = element.offsetWidth;
  const renderedWidth = element.getBoundingClientRect().width;
  if (layoutWidth > 0 && renderedWidth > 0) {
    const scale = renderedWidth / layoutWidth;
    if (Number.isFinite(scale) && scale > 0) return scale;
  }

  // Native compact CSS does not add a document-level scale. Keep the neutral
  // fallback for the pre-layout event rather than guessing from a stale style.
  return 1;
}
/**
 * 두 값만 **탭 세션** 동안 기억한다(localStorage가 아니다).
 *
 * - 담당자 이름은 감사 표식이지 인증이 아니다. 한 번 적고 여러 건에 다시 쓰는 값이므로
 *   화면을 오갈 때마다 다시 치게 하지 않는다. 브라우저를 닫으면 사라진다.
 * - 직전 사유는 **다시 쓰기 단추의 후보**일 뿐이다. 드롭다운은 여전히 빈 값에서 시작하고
 *   저장에 성공하면 비워진다(PRD §3.3) — 사람이 누를 때에만 채워진다.
 */
const LAST_REASON_STORAGE_KEY = "bidops.order-plans.lastTrackingReason";
const TRACKING_ACTOR_STORAGE_KEY = "bidops.order-plans.trackingActor";

type RelevanceToken = "relevant" | "uncertain" | "not_relevant" | "null";
type Stage1Token = "selected" | "filtered_out" | "failed" | "rejected" | "null";
type FeedbackToken = "has" | "none";
/** 보조 정보 대화상자 안의 두 탭. 기본 상세에서 뺀 신호·실행 기록이 여기 남는다. */
type SignalTab = "signals" | "telemetry";
/** 기본 검토 화면 밖으로 옮긴 보조 표시. 한 번에 하나만 연다. */
type SecondaryDialog = "signals" | "feedback" | "runtime";

const RELEVANCE_TOKENS: readonly RelevanceToken[] = ["relevant", "uncertain", "not_relevant", "null"];
const STAGE1_TOKENS: readonly Stage1Token[] = ["selected", "filtered_out", "failed", "rejected", "null"];
const FEEDBACK_TOKENS: readonly FeedbackToken[] = ["has", "none"];
const AXIS_KEYS = ["qwen", "stage1", "feedback", "issue", "q"] as const;

interface FilterAxes {
  qwen: RelevanceToken[];
  stage1: Stage1Token[];
  feedback: FeedbackToken[];
  issue: boolean;
}

interface Preset {
  key: string;
  label: string;
  description: string;
  axes: FilterAxes;
}

const PRESETS: Preset[] = [
  { key: "review", label: "검토 대상", description: "Qwen relevant 또는 uncertain", axes: { qwen: ["relevant", "uncertain"], stage1: [], feedback: [], issue: false } },
  { key: "all", label: "전체", description: "선택한 수집 회차 전체", axes: { qwen: [], stage1: [], feedback: [], issue: false } },
  { key: "bm25-filtered-out", label: "BM25 탈락", description: "BM25 Top 범위 밖", axes: { qwen: [], stage1: ["filtered_out"], feedback: [], issue: false } },
  { key: "failure", label: "실패·거부", description: "BM25 또는 Qwen 단계 실패·거부", axes: { qwen: [], stage1: [], feedback: [], issue: true } },
];

interface SavedView {
  id: string;
  name: string;
  search: string;
  createdAt: string;
}

function formatMoment(value: string | null | undefined): string {
  if (!value) return "미확인";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString("ko-KR");
}

function formatNumber(value: number | null | undefined): string {
  return value === null || value === undefined ? "null (미측정)" : value.toLocaleString("ko-KR");
}

function formatNullableMoment(value: string | null): string {
  return value === null ? "null" : formatMoment(value);
}

function formatScore(value: number | null): string {
  return value === null ? "null (값 없음/미측정)" : value.toLocaleString("ko-KR", { maximumFractionDigits: 4 });
}

function textOrUnknown(value: string | null | undefined): string {
  return value && value.trim() ? value : "미확인";
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

function plannedTiming(year: string | null, month: string | null): string {
  if (year === null && month === null) return "null (계획 시기 미제공)";
  // 실제 수집 값은 월만("09") 또는 연월("2026-09")이다. 같은 연도를
  // 두 번 표시하지 않으며, 서로 다른 연도나 누락값은 추정해 고치지 않는다.
  const monthOnly = year && month && /^\d{4}-\d{2}$/.test(month) && month.startsWith(`${year}-`)
    ? month.slice(5)
    : month;
  return `${year ?? "null"}년 ${monthOnly ?? "null"}월`;
}

function budgetLabel(value: number | null): string {
  return value === null ? "예산 null (미제공)" : formatCompactPrice(value);
}

/** 상세의 사실 표는 라벨이 따로 있으므로 값만 쓴다. null은 그대로 밝힌다. */
function budgetValue(value: number | null): string {
  return value === null ? "null (미제공)" : `${value.toLocaleString("ko-KR")}원`;
}

function stage1RowLabel(value: OrderPlanStage1Status | null): string {
  if (value === "selected") return "BM25 선정";
  if (value === "filtered_out") return "BM25 탈락";
  if (value === "failed") return "BM25 실패";
  if (value === "rejected") return "BM25 거부";
  return "BM25 결과 null";
}

/**
 * 시안과 같은 색 규칙: 실패·거부만 오류 색이고 나머지는 중립이다.
 *
 * 상태를 색으로 구분하지 않는다 — 목록의 거의 모든 행이 `BM25 선정`이라 그 색이 켜져
 * 있으면 화면이 온통 강조색이 되고, 정작 눈에 띄어야 할 실패가 묻힌다. 구분은 라벨이
 * 진다(`BM25 선정`·`BM25 탈락`·`BM25 실패`).
 */
function stage1BadgeVariant(value: OrderPlanStage1Status | null): "neutral" | "error" {
  if (value === "failed" || value === "rejected") return "error";
  return "neutral";
}

/** stage2_status 5값(not_attempted/success/failed/rejected/unknown)을 그대로 구분한다.
 * relevance가 null이라고 실패·거부·미시도·unknown을 전부 같은 문구로 뭉개지 않는다. */
function stage2Label(value: OrderPlanStage2Status | null): string {
  if (value === "not_attempted") return "Qwen 미시도";
  if (value === "success") return "Qwen 완료";
  if (value === "failed") return "Qwen 실패";
  if (value === "rejected") return "Qwen 거부";
  if (value === "unknown") return "Qwen unknown";
  return "Qwen 결과 null";
}

/** relevance가 있으면 relevance 문구를, 없으면(null) stage2_status로 이유를 구분해 보여준다.
 * qwen_relevance만 보면 not_attempted·failed·rejected·unknown이 전부 "null"로 뭉개지므로
 * (F1) 행과 신호 세부 탭 양쪽에서 이 함수 하나로 일관되게 표시한다. */
function qwenRowLabel(item: { qwen_relevance: OrderPlanRelevance | null; stage2_status: OrderPlanStage2Status | null }): string {
  if (item.qwen_relevance === "relevant") return "모델 관련";
  if (item.qwen_relevance === "uncertain") return "모델 판단 보류";
  if (item.qwen_relevance === "not_relevant") return "모델 비관련";
  return stage2Label(item.stage2_status);
}

/** stage1과 같은 규칙이다. 관련성은 한국어 라벨로 구분하고 원래 값은 신호 세부에서 읽는다. */
function qwenBadgeVariant(item: { qwen_relevance: OrderPlanRelevance | null; stage2_status: OrderPlanStage2Status | null }): "error" | "neutral" {
  if (item.stage2_status === "failed" || item.stage2_status === "rejected") return "error";
  return "neutral";
}

function relevanceToken(value: OrderPlanRelevance | null): RelevanceToken {
  return (value ?? "null") as RelevanceToken;
}

const RELEVANCE_PRIORITY: Readonly<Record<RelevanceToken, number>> = {
  relevant: 0,
  uncertain: 1,
  not_relevant: 2,
  null: 3,
};

/**
 * 검토 목록은 모델 relevance 신호만으로 우선순위를 정한다. 점수나 다른 상태를
 * 추론하지 않으며, 같은 relevance 안에서는 API가 준 순서를 보존한다.
 */
function sortByRelevance(items: readonly OrderPlanListItem[]): OrderPlanListItem[] {
  return items
    .map((item, index) => ({ item, index }))
    .sort((left, right) =>
      RELEVANCE_PRIORITY[relevanceToken(left.item.qwen_relevance)] - RELEVANCE_PRIORITY[relevanceToken(right.item.qwen_relevance)]
      || left.index - right.index,
    )
    .map(({ item }) => item);
}

function stage1Token(value: OrderPlanStage1Status | null): Stage1Token {
  return (value ?? "null") as Stage1Token;
}

function isExecutionIssue(item: OrderPlanListItem): boolean {
  const stage1Bad = item.stage1_status === "failed" || item.stage1_status === "rejected";
  const stage2Bad = item.stage2_status === "failed" || item.stage2_status === "rejected";
  return stage1Bad || stage2Bad;
}

/**
 * 축(Qwen·BM25·사람 피드백·실행 결과) 매칭만 떼어 낸 부분. 축 안은 OR, 축끼리는 AND다.
 *
 * 목록 필터와 보기 탭의 건수가 **같은 규칙 하나**를 읽게 하려고 나눴다. 탭 건수는 검색어를
 * 뺀 축만으로 세므로(검색은 탭이 아니라 입력이 소유한다) 검색 조건은 여기 없다.
 */
interface AxisSelection {
  qwenSet: Set<RelevanceToken>;
  stage1Set: Set<Stage1Token>;
  feedbackSet: Set<FeedbackToken>;
  issueOn: boolean;
}

function matchesAxes(item: OrderPlanListItem, axes: AxisSelection): boolean {
  if (axes.qwenSet.size && !axes.qwenSet.has(relevanceToken(item.qwen_relevance))) return false;
  if (axes.stage1Set.size && !axes.stage1Set.has(stage1Token(item.stage1_status))) return false;
  if (axes.feedbackSet.size) {
    const token: FeedbackToken = item.human_feedback ? "has" : "none";
    if (!axes.feedbackSet.has(token)) return false;
  }
  if (axes.issueOn && !isExecutionIssue(item)) return false;
  return true;
}

function presetSelection(preset: Preset): AxisSelection {
  return {
    qwenSet: new Set(preset.axes.qwen),
    stage1Set: new Set(preset.axes.stage1),
    feedbackSet: new Set(preset.axes.feedback),
    issueOn: preset.axes.issue,
  };
}

function statusTone(status: string | null | undefined): "success" | "warning" | "error" | "info" | "neutral" {
  if (status === "성공" || status === "relevant" || status === "selected") return "success";
  if (status === "부분 성공" || status === "uncertain" || status === "실행 중" || status === "중지 요청") return "warning";
  if (status === "실패" || status === "failed" || status === "rejected" || status === "not_relevant") return "error";
  if (status === "대기" || status === "unknown" || status === "not_attempted") return "info";
  return "neutral";
}

/** StatusDot은 success/warning/error/accent/neutral만 지원한다(Badge와 다름). */
function statusDotVariant(status: string | null | undefined): "success" | "warning" | "error" | "accent" | "neutral" {
  const tone = statusTone(status);
  return tone === "info" ? "accent" : tone;
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

function parseOrderPlanPk(value: string | null): number | null {
  if (value === null || !/^\d+$/.test(value)) return null;
  const parsed = Number(value);
  return Number.isSafeInteger(parsed) && parsed > 0 ? parsed : null;
}

function setEqualsArray<T>(set: Set<T>, values: readonly T[]): boolean {
  return set.size === values.length && values.every((value) => set.has(value));
}

/** 저장된 폭이 없으면 `null`이다. `null`은 "아직 비율 기본값"이라는 뜻이다. */
function loadListWidth(): number | null {
  try {
    const raw = window.localStorage.getItem(LIST_WIDTH_STORAGE_KEY);
    const parsed = raw ? Number(raw) : NaN;
    if (!Number.isFinite(parsed)) return null;
    return Math.min(MAX_LIST_WIDTH, Math.max(MIN_LIST_WIDTH, parsed));
  } catch {
    return null;
  }
}

function saveListWidth(width: number): void {
  try {
    window.localStorage.setItem(LIST_WIDTH_STORAGE_KEY, String(width));
  } catch {
    /* localStorage 접근 불가는 화면 동작을 막지 않는다 */
  }
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
  const first = await api.getOrderPlanScreeningExecutions({ limit: PAGE_SIZE, offset: 0 }, { signal });
  const items = [...first.items];
  const pageSize = first.limit > 0 ? first.limit : PAGE_SIZE;
  while (items.length < first.total) {
    const page = await api.getOrderPlanScreeningExecutions({ limit: pageSize, offset: items.length }, { signal });
    if (!page.items.length) break;
    items.push(...page.items);
  }
  return { ...first, items, offset: 0 };
}

async function fetchAllOrderPlans(sourceRunId: string, signal: AbortSignal): Promise<OrderPlanListResponse> {
  const first = await api.getOrderPlans({ source_run_id: sourceRunId, limit: PAGE_SIZE, offset: 0 }, { signal });
  const items = [...first.items];
  const pageSize = first.limit > 0 ? first.limit : PAGE_SIZE;
  while (items.length < first.total) {
    const page = await api.getOrderPlans({ source_run_id: sourceRunId, limit: pageSize, offset: items.length }, { signal });
    if (!page.items.length) break;
    items.push(...page.items);
  }
  return { ...first, items, offset: 0 };
}

function latestCompletedExecution(items: OrderPlanScreeningExecutionSummary[]): OrderPlanScreeningExecutionSummary | null {
  return items
    .filter((item) => item.status === "성공" || item.status === "부분 성공")
    .reduce<OrderPlanScreeningExecutionSummary | null>((latest, item) => {
      if (!latest) return item;
      const latestAt = Date.parse(latest.finished_at ?? latest.queued_at);
      const itemAt = Date.parse(item.finished_at ?? item.queued_at);
      if (itemAt > latestAt || (itemAt === latestAt && item.execution_id > latest.execution_id)) return item;
      return latest;
    }, null);
}

function executionHasProblem(latest: OrderPlanScreeningExecutionSummary | null, executions: OrderPlanScreeningExecutionSummary[]): boolean {
  if (!latest) return true;
  if (latest.status !== "성공") return true;
  if (!latest.execution_allowed) return true;
  return executions.some((item) => item.status === "대기" || item.status === "실행 중" || item.status === "중지 요청");
}

/** 실행 결과가 없거나 성공/부분 성공이 없을 때의 안내. 값 없음과 실패를 성공으로 바꾸지 않는다. */
function ExecutionMissingBlock({ executions }: { executions: OrderPlanScreeningExecutionSummary[] }) {
  if (!executions.length) {
    return <ReviewState
      kind="empty"
      title="C-2 실행 결과가 없습니다."
      description="성공 또는 부분 성공 실행이 없어 발주계획을 표시하지 않습니다. 결과 없음은 비관련로 해석하지 않습니다."
    />;
  }
  return (
    <ReviewState
      className="c2l-execution-empty"
      kind="failure"
      title="검토에 사용할 성공/부분 성공 결과가 없습니다."
      description={`실행 상태: ${executions.slice(0, 3).map((item) => `${item.status} (${item.execution_id})`).join(", ")}. 실패·중단·중지 상태를 성공 결과로 해석하지 않습니다.`}
    />
  );
}

/**
 * 상단 줄에 놓는 압축 실행 상태. 상태 낱말과 사람이 조치할 표식만 남기고
 * execution_id·시각·집계는 `실행 상태` 대화상자가 진다 — 기술 문자열이 화면 제목과
 * 자리를 다투면 제목이 읽히지 않는다.
 */
function ExecutionStatusChip({ latest, executions }: { latest: OrderPlanScreeningExecutionSummary | null; executions: OrderPlanScreeningExecutionSummary[] }) {
  const active = executions.filter((item) => item.status === "대기" || item.status === "실행 중" || item.status === "중지 요청");
  return (
    <span className="c2l-status-chip">
      <ReviewStatus
        label={latest ? latest.status : "실행 없음"}
        variant={latest ? statusDotVariant(latest.status) : "neutral"}
      />
      {latest && !latest.execution_allowed ? <Badge variant="error" label="모델 연결 비허용" /> : null}
      {active.length ? <Badge variant="warning" label={`진행 중 ${active.length}`} /> : null}
    </span>
  );
}

function ExecutionSummaryLine({ latest, executions }: { latest: OrderPlanScreeningExecutionSummary | null; executions: OrderPlanScreeningExecutionSummary[] }) {
  const active = executions.filter((item) => item.status === "대기" || item.status === "실행 중" || item.status === "중지 요청");
  if (!latest) {
    return (
      <Stack direction="horizontal" gap={2} align="center">
        <ReviewStatus
          label="실행 없음"
          variant="neutral"
          detail="표시할 성공/부분 성공 실행이 없습니다."
        />
      </Stack>
    );
  }
  return (
    <Stack direction="horizontal" gap={2} align="center" wrap="wrap">
      <ReviewStatus
        label={latest.status}
        variant={statusDotVariant(latest.status)}
        detail={`· ${latest.execution_id.slice(0, 8)} · ${formatMoment(latest.finished_at ?? latest.queued_at)}`}
      />
      {!latest.execution_allowed ? <Badge variant="error" label="정책·모델 연결 비허용" /> : null}
      {active.length ? <Badge variant="warning" label={`진행 중 실행 ${active.length}건`} /> : null}
    </Stack>
  );
}

/** BM25 rank/score/nearest capability와 Qwen score/reason. 목록 행에서 뺀 신호 세부다. */
function SignalPanel({ item }: { item: OrderPlanListItem }) {
  return (
    <div className="c2l-verdict">
      {/* source run·관측 시각은 기본 상세에서 뺐지만(시안) 삭제하지 않고 여기 남긴다(F3). */}
      <dl className="c2l-signal-facts">
        <div><dt>source run</dt><dd className="c2l-digest"><ReviewValue value={item.source_run_id} nullLabel="null (미제공)" /></dd></div>
        <div><dt>관측 시각</dt><dd>{formatMoment(item.observed_at)}</dd></div>
      </dl>
      <div className="c2l-signal-grid">
        <section className="c2l-signal" aria-labelledby={`c2l-bm25-${item.order_plan_pk}`}>
          <Heading level={5} id={`c2l-bm25-${item.order_plan_pk}`}>BM25 후보 신호</Heading>
          <dl className="c2l-signal-facts">
            <div><dt>status</dt><dd>{stage1RowLabel(item.stage1_status)}</dd></div>
            <div><dt>rank</dt><dd>{item.stage1_rank === null ? "null (값 없음/미측정)" : item.stage1_rank}</dd></div>
            <div><dt>score</dt><dd>{formatScore(item.stage1_score)}</dd></div>
            <div><dt>nearest capability</dt><dd><ReviewValue value={item.nearest_capability} nullLabel="null (미제공)" /></dd></div>
          </dl>
        </section>
        <section className="c2l-signal" aria-labelledby={`c2l-qwen-${item.order_plan_pk}`}>
          <Heading level={5} id={`c2l-qwen-${item.order_plan_pk}`}>Qwen relevance 신호</Heading>
          <dl className="c2l-signal-facts">
            {/* status(stage2_status)는 relevance와 별도 축이다: not_attempted·failed·rejected·unknown을
                relevance null 하나로 뭉개지 않는다(F1). */}
            <div><dt>status</dt><dd>{stage2Label(item.stage2_status)}</dd></div>
            <div><dt>relevance</dt><dd>{item.qwen_relevance ?? "null (값 없음/미적용)"}</dd></div>
            <div><dt>score</dt><dd>{formatScore(item.qwen_score)}</dd></div>
            <div><dt>reason</dt><dd><ReviewValue value={item.qwen_reason} nullLabel="null (근거 미제공)" /></dd></div>
          </dl>
        </section>
      </div>
    </div>
  );
}

/** model_digest·token 수·duration_ms·binding sha256·artifact 요약. 삭제하지 않고 이 탭으로 옮겼다. */
function TelemetryPanel({
  execution,
  detail,
  detailPending,
  detailError,
}: {
  execution: OrderPlanScreeningExecutionSummary;
  detail: OrderPlanScreeningExecutionDetailResponse | undefined;
  detailPending: boolean;
  detailError: unknown;
}) {
  const counts = execution.counts;
  return (
    <div className="c2l-telemetry">
      <div className="c2l-telemetry-heading">
        <div>
          <Text type="supporting" color="secondary" as="p">source run</Text>
          <Text type="body" color="primary" as="p">{execution.source_run_id}</Text>
          <Text type="supporting" color="secondary" as="p">{formatMoment(execution.finished_at ?? execution.queued_at)}</Text>
        </div>
        <Stack direction="horizontal" gap={2} align="center">
          <Badge variant={statusTone(execution.status) === "error" ? "error" : statusTone(execution.status) === "warning" ? "warning" : "neutral"} label={execution.status} />
          <Text type="body" color="secondary">{execution.execution_allowed ? "정책·모델 연결 허용" : "정책·모델 연결 비허용"}</Text>
        </Stack>
      </div>

      <dl className="c2l-fact-grid">
        <div><dt>execution_id</dt><dd className="c2l-digest">{execution.execution_id}</dd></div>
        <div><dt>요청자</dt><dd>{textOrUnknown(execution.requested_by)}</dd></div>
        <div><dt>policy version</dt><dd>{execution.policy_version}</dd></div>
        <div><dt>population</dt><dd>{formatNumber(execution.population_count)}건</dd></div>
        <div><dt>대상 hash</dt><dd className="c2l-digest">{execution.population_sha256}</dd></div>
        <div><dt>정책 해시</dt><dd className="c2l-digest">{execution.policy_sha256}</dd></div>
        <div><dt>모델 연결 상태</dt><dd>{execution.execution_allowed ? "허용됨" : "허용됨이 아님"}</dd></div>
        <div><dt>모델 연결 해시</dt><dd className="c2l-digest">{execution.binding_sha256}</dd></div>
      </dl>

      <dl className="c2l-fact-grid" aria-label="단계별 모델 연결">
        <div><dt>BM25 모델 연결</dt><dd>{execution.stage1_binding_version} · <span className="c2l-digest">{execution.stage1_binding_sha256}</span></dd></div>
        <div><dt>Qwen 모델 연결</dt><dd>{execution.stage2_binding_version} · <span className="c2l-digest">{execution.stage2_binding_sha256}</span></dd></div>
      </dl>

      <dl className="c2l-count-grid" aria-label="실행 집계">
        <div><dt>후보</dt><dd>{counts.candidate_count}</dd></div>
        <div><dt>완료</dt><dd>{counts.completed_count}</dd></div>
        <div><dt>실패</dt><dd>{counts.failure_count}</dd></div>
        <div><dt>BM25 선정</dt><dd>{counts.stage1_selected_count}</dd></div>
        <div><dt>BM25 탈락</dt><dd>{counts.stage1_filtered_out_count}</dd></div>
        <div><dt>BM25 실패</dt><dd>{counts.stage1_failed_count}</dd></div>
        <div><dt>Qwen relevant</dt><dd>{counts.stage2_relevant_count}</dd></div>
        <div><dt>Qwen not relevant</dt><dd>{counts.stage2_not_relevant_count}</dd></div>
        <div><dt>Qwen uncertain</dt><dd>{counts.stage2_uncertain_count}</dd></div>
        <div><dt>Qwen 실패</dt><dd>{counts.stage2_failed_count}</dd></div>
        <div><dt>Qwen 거부</dt><dd>{counts.stage2_rejected_count}</dd></div>
        <div><dt>사람 검토</dt><dd>{counts.human_review_count}</dd></div>
      </dl>

      <div className="c2l-telemetry-attempts">
        <Heading level={5}>실행 모델 · 수정본 · 프롬프트 · 프로필 · 분석 회차</Heading>
        {detailPending ? <Text type="body" color="secondary" as="p">실행 artifact 요약을 불러오는 중…</Text> : null}
        {detailError ? <Text type="body" color="secondary" as="p" data-role="alert">실행 상세를 불러오지 못해 산출물·분석 회차 요약을 확인할 수 없습니다.</Text> : null}
        {detail?.attempts.length ? (
          <ol className="c2l-attempt-list">
            {detail.attempts.map((attempt) => (
              <li key={attempt.attempt_id}>
                <Text type="body" color="primary" weight="semibold" as="p">batch {attempt.batch_id} · attempt {attempt.attempt_no}</Text>
                <dl className="c2l-attempt-grid">
                  <div><dt>model / revision</dt><dd>{attempt.model_name} · <span className="c2l-digest">{attempt.model_digest}</span></dd></div>
                  <div><dt>prompt</dt><dd>{attempt.prompt_version} · <span className="c2l-digest">{attempt.prompt_sha256}</span></dd></div>
                  <div><dt>profile</dt><dd>{attempt.company_profile_version} · <span className="c2l-digest">{attempt.company_profile_sha256}</span></dd></div>
                  <div><dt>generation config</dt><dd className="c2l-digest">{attempt.generation_config_sha256}</dd></div>
                  <div><dt>status</dt><dd><Badge variant={attempt.attempt_status === "success" ? "success" : attempt.attempt_status === "running" ? "warning" : "error"} label={attempt.attempt_status} /></dd></div>
                  <div><dt>failure</dt><dd>{attempt.failure_type ?? "null"} · {attempt.failure_code ?? "null"}</dd></div>
                  <div><dt>tokens (input / cached / output / total)</dt><dd>{formatNumber(attempt.input_tokens)} / {formatNumber(attempt.cached_input_tokens)} / {formatNumber(attempt.output_tokens)} / {formatNumber(attempt.total_tokens)}</dd></div>
                  <div><dt>duration_ms</dt><dd>{formatNumber(attempt.duration_ms)}</dd></div>
                  <div><dt>시각</dt><dd>{formatNullableMoment(attempt.started_at)} → {formatNullableMoment(attempt.finished_at)}</dd></div>
                </dl>
              </li>
            ))}
          </ol>
        ) : detail ? <Text type="body" color="secondary" as="p">분석 회차 기록 없음 (서버 응답)</Text> : null}
        <dl className="c2l-fact-grid">
          <div><dt>partial artifact</dt><dd>{execution.partial_artifact ? "있음" : "없음"}</dd></div>
          <div><dt>error code</dt><dd>{execution.error_code === null ? "null (서버 미제공)" : execution.error_code}</dd></div>
        </dl>
      </div>

      {detail?.artifacts.length ? (
        <div className="c2l-artifact-summary">
          <Heading level={5}>안전한 artifact 요약</Heading>
          <ul>
            {detail.artifacts.map((artifact) => (
              <li key={`${artifact.kind}-${artifact.sha256}`}>
                <span>{artifact.kind}</span>
                <Badge variant={artifact.validation_status === "valid" ? "success" : artifact.validation_status === "invalid" ? "error" : "warning"} label={artifact.validation_status} />
                <span>{artifact.byte_count.toLocaleString("ko-KR")} bytes</span>
                <span className="c2l-digest">{artifact.sha256}</span>
              </li>
            ))}
          </ul>
          <Text type="supporting" color="secondary" as="p">본문·원문 경로·다운로드 URL은 이 화면에서 노출하지 않습니다.</Text>
        </div>
      ) : null}
    </div>
  );
}

/**
 * 추적 결정(결정 1)의 사유 선택지.
 *
 * 사용자가 승인한 시안(focus-v2)의 목록이 정본이다. 화면은 사유를 자동으로 고르지
 * 않고 사람이 고른 값만 계약에 싣는다. `기타 · 직접 입력`은 값이 아니라 자유 입력을
 * 여는 표식이므로 저장되는 것은 사람이 적은 문장이다.
 */
const TRACKING_REASONS = [
  "후속 사전규격·공고 확인",
  "사업 방향이 관심 분야와 맞음",
  "예산·시기 추가 확인 필요",
  "세부 과업 확인 후 판단",
  "현재 검토 범위와 맞지 않음",
  "중복·오탐으로 확인",
] as const;

/** 자유 입력을 여는 선택지의 값. 사유 문자열이 아니라 표식이므로 계약에 싣지 않는다. */
const OTHER_REASON = "other";

const TRACKING_REASON_OPTIONS = [
  ...TRACKING_REASONS.map((value) => ({ label: value, value })),
  { label: "기타 · 직접 입력", value: OTHER_REASON },
];

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
 * 추적 결정을 기록할 수 있는지의 세 상태. 서로 바꾸지 않는다.
 *
 * - `contract_missing`: 응답에 `tracking`이 없다. 서버 계약이 아직 없다는 뜻이며
 *   `미선택`이 아니다 (요청안 §7 규칙 3).
 * - `opportunity_missing`: `tracking`이 `null`이다. 이 발주계획을 소유한 사업기회를
 *   확인하지 못했다.
 * - `available`: 추적 상태를 읽었다. 그 값이 `미선택`일 수 있고, 미선택은 종료가 아니다.
 */
type TrackingAvailability = "available" | "contract_missing" | "opportunity_missing";

function trackingAvailability(item: OrderPlanListItem | null): TrackingAvailability {
  if (item && !("tracking" in item)) return "contract_missing";
  if (!item || item.tracking == null) return "opportunity_missing";
  return "available";
}

function trackingStatusLabel(item: OrderPlanListItem | null): string {
  switch (trackingAvailability(item)) {
    case "contract_missing":
      return "계약 미구현";
    case "opportunity_missing":
      return "사업기회 미연결";
    default:
      return item?.tracking?.tracking_status === "미선택"
        ? "추적 결정 없음"
        : (item?.tracking?.tracking_status ?? "추적 결정 없음");
  }
}

/**
 * 상세 pane 바닥의 추적 결정 입력.
 *
 * 시안(focus-v2)의 결정 블록은 늘 보이는 한 덩어리다: 머리줄(추적 선택 · 현재 상태 ·
 * 위치), 사유 드롭다운과 담당자 감사 표식 한 줄, `기타`일 때만 열리는 자유 입력.
 * 결정 버튼과 안내 한 줄은 `ReviewDecisionBar`의 action·hint 자리에 있다.
 *
 * 상태의 뜻을 길게 설명하는 문장은 여기 두지 않는다. 현재 상태는 badge가, 저장할 수
 * 없는 이유는 결정 줄 아래 한 문장이, 나머지 구분 규칙은 `실행 상태` 대화상자가 진다.
 */
function TrackingDecisionFields({
  item,
  reasonChoice,
  onReasonChoiceChange,
  customReason,
  onCustomReasonChange,
  actorName,
  onActorNameChange,
  position,
  lastReason,
  onReuseLastReason,
  sectionRef,
  isDisabled = false,
}: {
  item: OrderPlanListItem;
  reasonChoice: string;
  onReasonChoiceChange: (value: string) => void;
  customReason: string;
  onCustomReasonChange: (value: string) => void;
  actorName: string;
  onActorNameChange: (value: string) => void;
  position: string;
  /** 이 탭에서 마지막으로 **저장에 성공한** 사유. 없으면 빈 문자열이다. */
  lastReason: string;
  onReuseLastReason: () => void;
  sectionRef: Ref<HTMLElement>;
  isDisabled?: boolean;
}) {
  const availability = trackingAvailability(item);
  /** 지금 계약에 실릴 사유. 이 값이 이미 있으면 다시 쓰기 단추를 그리지 않는다. */
  const currentReason = reasonChoice === OTHER_REASON ? customReason.trim() : reasonChoice;
  return (
    <section className="c2l-tracking" aria-labelledby={`c2l-tracking-${item.order_plan_pk}`} ref={sectionRef}>
      <header className="c2l-tracking-head">
        <Text type="label" color="primary" as="p" id={`c2l-tracking-${item.order_plan_pk}`}>추적 선택</Text>
        <Badge
          variant={availability === "available" ? "neutral" : "warning"}
          label={trackingStatusLabel(item)}
        />
        <Text type="supporting" color="secondary" as="p" className="c2l-tracking-position">{position}</Text>
      </header>
      <div className="c2l-tracking-fields">
        <div className="c2l-reason-field">
          <Selector
            label="선택 사유"
            onChange={(value) => onReasonChoiceChange(value ?? "")}
            options={TRACKING_REASON_OPTIONS}
            placeholder="사유를 선택하세요"
            size="sm"
            value={reasonChoice || undefined}
            isDisabled={isDisabled}
          />
          {/* 드롭다운을 미리 채우지 않는다(PRD §3.3). 직전 사유는 **사람이 누를 때에만**
              들어가는 후보이고, 무엇이 들어갈지 단추 이름이 그대로 말한다. */}
          {lastReason && !currentReason ? (
            /* 긴 사유는 CSS가 말줄임하므로 전문은 `title`이 진다. Astryx `Button`은
               `title`을 받지 않아(BaseProps가 뺀다) 감싸는 span이 그 자리다. */
            <span className="c2l-reason-reuse" title={lastReason}>
              <Button
                label={`직전 사유 다시 쓰기 · ${lastReason}`}
                onClick={onReuseLastReason}
                size="sm"
                variant="ghost"
                isDisabled={isDisabled}
              />
            </span>
          ) : null}
        </div>
        <TextInput
          label="담당자 이름 · 감사 표식"
          size="sm"
          value={actorName}
          onChange={onActorNameChange}
          placeholder="이름 입력"
          isDisabled={isDisabled}
        />
      </div>
      {reasonChoice === OTHER_REASON ? (
        <TextInput
          label="선택 사유 직접 입력"
          size="sm"
          value={customReason}
          onChange={onCustomReasonChange}
          placeholder="추적·보류·종료를 선택한 이유를 적어주세요"
          isDisabled={isDisabled}
        />
      ) : null}
    </section>
  );
}

function OrderPlanRow({
  item,
  isSelected,
  isChecked,
  onCheckedChange,
  disabled = false,
  onKeyDown,
  onSelect,
  rowProps,
}: {
  item: OrderPlanListItem;
  isSelected: boolean;
  isChecked: boolean;
  onCheckedChange: (checked: boolean) => void;
  disabled?: boolean;
  /** 화면 단축키(Ctrl+Enter). `preventDefault()`하면 행 선택·↑↓ 이동보다 먼저다. */
  onKeyDown: (event: ReactKeyboardEvent<HTMLElement>) => void;
  onSelect: () => void;
  /** `useRowKeyboardNavigation`의 roving tabindex와 행 식별자. */
  rowProps: RowKeyboardNavigationRowProps;
}) {
  // BM25 `선정`은 목록의 거의 모든 행에 붙는 값이라 배지로 그리면 아무것도 구분하지
  // 못한다. 탈락·실패·거부·null만 남긴다 — 숨기는 것은 **기본값 하나**이고, 값이
  // 없거나 실패한 사실은 그대로 보인다.
  const stage1Badge = item.stage1_status !== "selected"
    ? <Badge variant={stage1BadgeVariant(item.stage1_status)} label={stage1RowLabel(item.stage1_status)} />
    : null;
  const feedbackBadge = item.human_feedback
    ? <Badge variant="neutral" label={`피드백 수정본 ${item.human_feedback.revision}`} />
    : null;
  return (
    <DenseListRow
      {...rowProps}
      aria-label={textOrUnknown(item.title)}
      className={`c2l-row-wrap c2l-row${isSelected ? " is-selected" : ""}`.trim()}
      description={
        <span className="c2l-row-desc">
          {/* 시안의 차례 그대로다: 사업명 아래 상태 배지, 그 아래 metadata 줄. 발주기관은
              자리를 옮기지 않고 metadata 줄의 첫 항목이며, 굵기를 주지 않는다. 목록에서
              먼저 읽혀야 하는 것은 사업명이다(사용자 정정).
              그릴 배지가 하나도 없으면 줄 자체를 만들지 않는다 — 빈 줄이 행마다 다른
              높이를 만들면 밀집 목록이 흔들린다. */}
          {stage1Badge || feedbackBadge ? (
            <span className="c2l-row-badges">
              {stage1Badge}
              {feedbackBadge}
            </span>
          ) : null}
          <span className="c2l-row-meta" title={`예산 ${budgetValue(item.budget_amount)}`}>
            <Text className="c2l-row-agency" type="body" color="primary" as="span">
              {textOrUnknown(item.agency_name)}
            </Text>
            <Text type="supporting" color="secondary" as="span">
              · {budgetLabel(item.budget_amount)} · {plannedTiming(item.planned_order_year, item.planned_order_month)}
            </Text>
          </span>
        </span>
      }
      label={
        <span className="c2l-row-line c2l-row-head">
          {/* 긴 한글 제목은 한 줄에 담기지 않는다. 두 줄까지 보이고 그 뒤를 말줄임한다.
              크기와 굵기는 `.c2l-row-title`이 본문보다 한 단 위로 올린다. */}
          <Text className="c2l-row-title" type="body" color="primary" weight="semibold" maxLines={2}>{textOrUnknown(item.title)}</Text>
          {/* 모델 판단은 이 목록을 훑는 이유이므로 행마다 같은 자리(우상단)에서 읽힌다.
              baseline 정렬이라 제목이 두 줄로 잘려도 배지는 첫 줄에 붙어 있다. */}
          <Badge className="c2l-row-model" variant={qwenBadgeVariant(item)} label={qwenRowLabel(item)} />
        </span>
      }
      onKeyDown={onKeyDown}
      onSelect={onSelect}
      selected={isSelected}
      disabled={disabled}
      selection={{
        checked: isChecked,
        onCheckedChange,
        ariaLabel: `${textOrUnknown(item.title)} 선택`,
      }}
    />
  );
}

export function OrderPlansPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const queryClient = useQueryClient();

  const [searchText, setSearchText] = useState(searchParams.get("q") ?? "");
  const [signalTab, setSignalTab] = useState<SignalTab>("signals");
  const [dialog, setDialog] = useState<SecondaryDialog | null>(null);
  const [bulkDialogOpen, setBulkDialogOpen] = useState(false);
  const [bulkPending, setBulkPending] = useState(false);
  const [bulkRecoveryAvailable, setBulkRecoveryAvailable] = useState(() => hasPendingOrderPlanBulkTrackingRequest());
  const [advancedOpen, setAdvancedOpen] = useState(false);
  // `null`이면 시안의 38% 비율을 그대로 쓴다. 사람이 끌거나 화살표를 누르면 px 로 고정된다.
  const [listWidth, setListWidth] = useState<number | null>(() => loadListWidth());
  const [measuredListWidth, setMeasuredListWidth] = useState<number | null>(null);
  const listPaneRef = useRef<HTMLElement | null>(null);
  // ↑↓ 이동은 목록 `<ul>`에 리스너를 단다(window 전역이 아니다) — 상세 pane 입력과
  // 리사이즈 손잡이의 방향키가 같은 화면에서 서로 경쟁하지 않는다.
  const listRef = useRef<HTMLUListElement | null>(null);
  const trackingSectionRef = useRef<HTMLElement | null>(null);
  const [savedViews, setSavedViews] = useState<SavedView[]>(() => loadSavedViews());
  const [newViewName, setNewViewName] = useState("");
  const [isNamingView, setIsNamingView] = useState(false);

  // 사유는 자동으로 고르지 않는다. 빈 값이 기본이고, `기타`를 골라야 자유 입력이 열린다.
  // 같은 건에서 선택지를 왕복해도 적어 둔 자유 입력은 남긴다(시안 §3).
  const [reasonChoice, setReasonChoice] = useState("");
  const [customReason, setCustomReason] = useState("");
  // 담당자는 감사 표식이고 여러 건에 다시 쓰는 값이라 탭 세션 동안 기억한다.
  const [trackingActor, setTrackingActor] = useState(() => loadSessionValue(TRACKING_ACTOR_STORAGE_KEY));
  // 저장에 성공한 마지막 사유. 드롭다운을 채우지 않고 `직전 사유 다시 쓰기` 단추만 만든다.
  const [lastReason, setLastReason] = useState(() => loadSessionValue(LAST_REASON_STORAGE_KEY));
  // 추적 `종료`만 되돌릴 수 없다. 확인 문구는 사전규격·사업 추적과 같은 자리에서
  // 만들어 세 화면이 다른 말을 하지 않게 한다.
  const [endConfirm, setEndConfirm] = useState<ReturnType<typeof trackingEndConfirmContent> | null>(null);
  // 결정 뒤의 안내는 **이동한 뒤의 건**에 붙는다. 선택이 바뀌면 사라지되, 그 이동을 만든
  // 결정의 안내는 남아야 하므로 어느 건에서 보일 문구인지를 함께 들고 다닌다.
  const [trackingMessage, setTrackingMessage] = useState<{ pk: number; text: string } | null>(null);

  const [relevance, setRelevance] = useState<OrderPlanRelevance>("uncertain");
  const [priority, setPriority] = useState<OrderPlanFeedbackPriority | "">("");
  const [memo, setMemo] = useState("");
  const [actorName, setActorName] = useState("");
  const [savedMessage, setSavedMessage] = useState<string | null>(null);
  // 저장 기준점. 저장에 성공하면 그때의 값이 새 기준이 되어 "저장되지 않은 입력"이
  // 풀린다. 값 자체는 그대로 두므로 사람은 방금 저장한 내용을 계속 볼 수 있다.
  const [feedbackBaseline, setFeedbackBaseline] = useState<FeedbackDraft>(EMPTY_FEEDBACK_DRAFT);
  const dragStateRef = useRef<{ startX: number; startWidth: number; renderedScale: number } | null>(null);

  const feedbackDirty = relevance !== feedbackBaseline.relevance
    || priority !== feedbackBaseline.priority
    || memo !== feedbackBaseline.memo;
  // 사유는 저장하면 다음 건으로 옮겨 가며 비워지므로 기준값은 늘 "빈 값"이다.
  const reasonDirty = reasonChoice !== "" || customReason.trim() !== "";
  /** 계약에 실을 사유. `기타`는 사람이 적은 문장 그대로이고 공백만 있으면 사유가 없다. */
  const trackingReason = reasonChoice === OTHER_REASON ? customReason.trim() : reasonChoice;

  const feedbackDraftSummary = [
    { label: "사람 판단 수정", value: `relevance ${relevance} · priority ${priority || "미지정"}` },
    { label: "memo", value: memo.trim() || "값 없음" },
  ];
  const reasonDraftSummary = [{ label: "선택 사유 초안", value: trackingReason || "직접 입력 미완료" }];
  const rowDraftSummary = [
    ...(feedbackDirty ? feedbackDraftSummary : []),
    ...(reasonDirty ? reasonDraftSummary : []),
    ...(bulkPending ? [{ label: "일괄 추적 요청", value: "저장 결과 확인 전까지 요청과 선택을 보호합니다." }] : []),
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
    title: "발주계획 검토 화면을 떠납니다",
    message: "저장하지 않은 입력 또는 확인 중인 일괄 요청이 있습니다. 지금 이동하면 입력이 사라지거나 요청 결과를 놓칠 수 있습니다.",
    summary: rowDraftSummary,
  });

  /**
   * 선택한 행이 바뀌는 조작. 사람 판단 수정 입력과 선택 사유가 사라지므로 그 둘만
   * 묻는다. 담당자 이름은 행이 바뀌어도 남으므로 여기서 잃는다고 말하지 않는다.
   */
  function withRowGuard(run: () => void) {
    guard.confirmDiscard(run, {
      dirty: feedbackDirty || reasonDirty || bulkPending,
      title: "다른 발주계획으로 이동합니다",
      message: bulkPending
        ? "일괄 추적 요청이 결과 확인 중입니다. 이동하면 요청과 선택을 잃을 수 있습니다."
        : "저장하지 않은 사람 판단 수정 입력과 선택 사유는 이 발주계획을 떠나면 사라집니다. 담당자 이름은 그대로 남습니다.",
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
      title: "다른 발주계획으로 이동합니다",
      message: "저장하지 않은 사람 판단 수정 입력은 이 발주계획을 떠나면 사라집니다. 담당자 이름은 그대로 남습니다.",
      summary: feedbackDraftSummary,
    });
  }

  useEffect(() => setSearchText(searchParams.get("q") ?? ""), [searchParams]);

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

  const runsQuery = useQuery({
    queryKey: ["runs"],
    queryFn: () => api.getRuns(),
    staleTime: 15_000,
  });
  const executionsQuery = useQuery({
    queryKey: ["order-plan-c2", "executions"],
    queryFn: ({ signal }) => fetchAllExecutions(signal),
    staleTime: 15_000,
  });
  const executions = executionsQuery.data?.items ?? [];
  const collectionRuns = (runsQuery.data?.items ?? [])
    .filter((run) => run.kind === "order_plans" || run.kind === "mixed")
    .sort((a, b) => b.generated_at.localeCompare(a.generated_at));
  const requestedSourceRunId = searchParams.get("source_run_id")?.trim() || null;
  const fallbackSourceRunId = collectionRuns[0]?.run_id
    ?? latestCompletedExecution(executions)?.source_run_id;
  /**
   * Opportunity links and old `/order-plans/:pk` bookmarks carry only the plan
   * PK. Resolve its immutable observation lineage before choosing the list
   * source. A source explicitly present in the URL always wins, so changing the
   * run selector or reopening a saved URL cannot silently move to another run.
   */
  const deepLinkPlanQuery = useQuery({
    queryKey: ["order-plan-c2", "deep-link-plan", selectedPk],
    queryFn: ({ signal }) => api.getOrderPlan(selectedPk as number, { signal }),
    enabled: isExplicitDeepLink && selectedPk !== null && !requestedSourceRunId,
    staleTime: 15_000,
  });
  const deepLinkSourceRunId = deepLinkPlanQuery.data?.observations[0]?.source_run_id ?? null;
  // While an explicit PK is being resolved, do not fetch the default run. That
  // temporary result could show a same-PK row from the wrong observation run.
  const sourceRunId = requestedSourceRunId
    ?? (isExplicitDeepLink && selectedPk !== null ? deepLinkSourceRunId : fallbackSourceRunId);

  // A fallback run is only provisional until the collection/execution queries
  // resolve. Pin the effective run in the URL once it is known so a refresh,
  // page change, or selection hydration cannot silently move to another run.
  // Explicit source/deep-link lineage always remains authoritative.
  useEffect(() => {
    if (requestedSourceRunId || isExplicitDeepLink || !sourceRunId) return;
    const params = new URLSearchParams(searchParams);
    params.set("source_run_id", sourceRunId);
    setSearchParams(params, { replace: true });
  }, [isExplicitDeepLink, requestedSourceRunId, searchParams, setSearchParams, sourceRunId]);

  useEffect(() => {
    if (!isExplicitDeepLink || selectedPk === null || requestedSourceRunId || deepLinkPlanQuery.isPending || deepLinkPlanQuery.isError || !deepLinkSourceRunId) return;
    const params = new URLSearchParams(searchParams);
    params.set("source_run_id", deepLinkSourceRunId);
    setSearchParams(params, { replace: true });
  }, [deepLinkPlanQuery.isError, deepLinkPlanQuery.isPending, deepLinkSourceRunId, isExplicitDeepLink, requestedSourceRunId, searchParams, selectedPk, setSearchParams]);

  const scopedExecutions = sourceRunId ? executions.filter((execution) => execution.source_run_id === sourceRunId) : executions;
  const latestExecution = latestCompletedExecution(scopedExecutions);
  const runOptions = Array.from(new Set([
    ...collectionRuns.map((run) => run.run_id),
    ...executions.map((execution) => execution.source_run_id),
    ...(sourceRunId ? [sourceRunId] : []),
  ])).map((runId) => {
    const run = collectionRuns.find((item) => item.run_id === runId);
    // 회차 이름은 서버가 준 metadata에서만 만든다. metadata가 없으면 날짜를 지어내지
    // 않고 회차 식별자를 줄여 보이고 전체 값은 description으로 남긴다.
    return {
      label: run
        ? (run.window_from && run.window_to
          ? `${run.window_from}~${run.window_to} 수집`
          : `${formatMoment(run.generated_at)} 수집`)
        : `회차 ${runId.slice(0, 8)}…`,
      description: runId,
      value: runId,
    };
  });

  function changeSourceRun(runId: string | null) {
    if (!runId) return;
    withRowGuard(() => {
      const params = new URLSearchParams();
      params.set("source_run_id", runId);
      params.set("qwen", "");
      setSearchText("");
      setSearchParams(params);
    });
  }

  // Keep the normal review default while resolving a selected row. Once the
  // target and execution scope are known, the targeted reset effect below
  // removes only filters that hide that record (for example `not_relevant`).
  const isDefaultView = Boolean(latestExecution) && !AXIS_KEYS.some((key) => searchParams.has(key));
  const qwenSet = isDefaultView ? new Set<RelevanceToken>(["relevant", "uncertain"]) : parseTokenSet(searchParams.get("qwen"), RELEVANCE_TOKENS);
  const stage1Set = isDefaultView ? new Set<Stage1Token>() : parseTokenSet(searchParams.get("stage1"), STAGE1_TOKENS);
  const feedbackSet = isDefaultView ? new Set<FeedbackToken>() : parseTokenSet(searchParams.get("feedback"), FEEDBACK_TOKENS);
  const issueOn = !isDefaultView && searchParams.get("issue") === "yes";
  const qText = searchParams.get("q") ?? "";
  const offsetRaw = Number(searchParams.get("offset") ?? "0");
  const offset = Number.isFinite(offsetRaw) && offsetRaw >= 0 ? Math.floor(offsetRaw / PAGE_SIZE) * PAGE_SIZE : 0;
  const selectionFingerprint = orderPlansFilterFingerprint({
    sourceRunId: sourceRunId ?? null,
    qwen: qwenSet,
    stage1: stage1Set,
    feedback: feedbackSet,
    issue: issueOn,
    q: qText,
  });
  const selectionHydrationReady = Boolean(sourceRunId)
    && !executionsQuery.isPending
    && !(isExplicitDeepLink && !requestedSourceRunId && deepLinkPlanQuery.isPending);
  const orderPlanSelection = useListSelection<number>({
    storageKey: ORDER_PLANS_SELECTION_STORAGE_KEY,
    filterFingerprint: selectionFingerprint,
    hydrationReady: selectionHydrationReady,
    // A selected URL target owns only active/source/page context. Checked
    // membership is an independent tab-session state and must still restore
    // when the browser reloads an automatically selected URL.
    restoreStoredState: true,
  });

  const activePreset = (() => {
    if (qText) return null;
    for (const preset of PRESETS) {
      if (
        setEqualsArray(qwenSet, preset.axes.qwen)
        && setEqualsArray(stage1Set, preset.axes.stage1)
        && setEqualsArray(feedbackSet, preset.axes.feedback)
        && issueOn === preset.axes.issue
      ) return preset.key;
    }
    return null;
  })();

  // 아래 네 함수는 확인 단계를 갖지 않는 원본이다. 확인은 사람이 누르는 자리
  // (`changeAxes`, `applyPreset`, `applySavedViewSearch`, `resetFilters`, 페이지 이동)가
  // 한 번만 건다. 원본끼리 겹쳐 부르면 같은 질문이 두 번 뜬다.
  function applyAxes(next: { qwen?: Set<RelevanceToken>; stage1?: Set<Stage1Token>; feedback?: Set<FeedbackToken>; issue?: boolean; q?: string }) {
    const params = new URLSearchParams(searchParams);
    if (next.qwen) params.set("qwen", serializeTokens(next.qwen));
    if (next.stage1) params.set("stage1", serializeTokens(next.stage1));
    if (next.feedback) params.set("feedback", serializeTokens(next.feedback));
    if (next.issue !== undefined) params.set("issue", next.issue ? "yes" : "");
    if (next.q !== undefined) params.set("q", next.q);
    params.delete("offset");
    setSearchParams(params, { replace: true });
    if (next.q !== undefined) orderPlanSelection.setListSearch(next.q);
  }

  /** 사람이 누르는 필터 축. 필터가 바뀌면 선택한 행도 바뀌므로 먼저 확인한다. */
  function changeAxes(next: { qwen?: Set<RelevanceToken>; stage1?: Set<Stage1Token>; feedback?: Set<FeedbackToken>; issue?: boolean; q?: string }) {
    withRowGuard(() => applyAxes(next));
  }

  function applyPreset(presetKey: string) {
    const preset = PRESETS.find((item) => item.key === presetKey);
    if (!preset) return;
    withRowGuard(() => {
      applyAxes({
        qwen: new Set(preset.axes.qwen),
        stage1: new Set(preset.axes.stage1),
        feedback: new Set(preset.axes.feedback),
        issue: preset.axes.issue,
        q: "",
      });
      setSearchText("");
    });
  }

  function applySavedViewSearch(search: string) {
    withRowGuard(() => {
      const savedParams = new URLSearchParams(search);
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
      params.delete("offset");
      setSearchParams(params, { replace: true });
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
    params.set("issue", issueOn ? "yes" : "");
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

  const listQuery = useQuery({
    queryKey: ["order-plan-c2", "list", sourceRunId],
    queryFn: ({ signal }) => fetchAllOrderPlans(sourceRunId as string, signal),
    enabled: Boolean(sourceRunId),
    staleTime: 15_000,
  });

  const executionDetailQuery = useQuery({
    queryKey: ["order-plan-c2", "execution-detail", latestExecution?.execution_id],
    queryFn: ({ signal }) => api.getOrderPlanScreeningExecution(latestExecution?.execution_id as string, { signal }),
    enabled: Boolean(latestExecution?.execution_id),
    staleTime: 15_000,
  });

  function matchesFilters(item: OrderPlanListItem): boolean {
    if (!matchesAxes(item, { qwenSet, stage1Set, feedbackSet, issueOn })) return false;
    if (qText) {
      // 시안의 검색은 사업명과 발주기관을 함께 본다. 계획번호는 기존 능력이므로 남긴다.
      const haystack = `${item.title ?? ""} ${item.agency_name ?? ""} ${item.order_plan_unty_no}`.toLocaleLowerCase("ko-KR");
      if (!haystack.includes(qText.toLocaleLowerCase("ko-KR"))) return false;
    }
    return true;
  }

  const allItems = listQuery.data?.items ?? [];
  /**
   * 보기 탭 옆의 건수. 지금 필터가 아니라 **각 탭을 눌렀을 때 남을 건수**이므로 검색어를
   * 빼고 그 탭의 축만 적용해 센다. 목록을 아직 못 읽었으면 0이 아니라 `null`(미확인)이다.
   */
  const presetCounts = useMemo(() => {
    const items = listQuery.data?.items;
    const counts = new Map<string, number | null>();
    for (const preset of PRESETS) {
      counts.set(preset.key, items ? items.filter((item) => matchesAxes(item, presetSelection(preset))).length : null);
    }
    return counts;
  }, [listQuery.data]);
  // 필터 결과 전체를 먼저 relevance 우선순위로 정렬한 뒤 잘라야 페이지와 ↑↓ 이동이
  // 같은 검토 순서를 공유한다. null은 값 없음으로만 다루고 다른 상태로 보정하지 않는다.
  const filteredItems = sortByRelevance(allItems.filter(matchesFilters));
  const total = filteredItems.length;
  const visibleItems = filteredItems.slice(offset, offset + PAGE_SIZE);
  const hasPrevious = offset > 0;
  const hasNext = offset + visibleItems.length < total;

  const explicitTargetItem = selectedPk !== null
    ? allItems.find((item) => item.order_plan_pk === selectedPk) ?? null
    : null;
  const invalidSelectedParam = selectedParam !== null && selectedPk === null;
  const explicitTargetInFilteredItems = selectedPk !== null
    && filteredItems.some((item) => item.order_plan_pk === selectedPk);
  const deepLinkNeedsSource = isExplicitDeepLink && selectedPk !== null && !requestedSourceRunId;
  const deepLinkPending = isExplicitDeepLink && selectedPk !== null && (
    (deepLinkNeedsSource && !deepLinkPlanQuery.data && !deepLinkPlanQuery.isError)
    || (Boolean(sourceRunId) && listQuery.isPending)
    // Do not consume the deep-link before the execution scope is known. The
    // normal default review view is derived from that scope and could hide the
    // requested row on the next render, allowing the ordinary first-row
    // fallback to select a different record.
    || executionsQuery.isPending
  );
  const deepLinkFailed = isExplicitDeepLink && (
    invalidSelectedParam
    || deepLinkPlanQuery.isError
    || listQuery.isError
    || (deepLinkNeedsSource && Boolean(deepLinkPlanQuery.data) && !deepLinkSourceRunId)
    || (!listQuery.isPending && !deepLinkPending && explicitTargetItem === null)
  );
  const selectedItem = invalidSelectedParam
    ? null
    : isExplicitDeepLink
    ? (deepLinkPending || deepLinkFailed || !explicitTargetInFilteredItems
      ? null
      : filteredItems.find((item) => item.order_plan_pk === selectedPk) ?? null)
    : ((selectedPk !== null
      ? filteredItems.find((item) => item.order_plan_pk === selectedPk)
      : orderPlanSelection.activeId !== null
        ? filteredItems.find((item) => item.order_plan_pk === orderPlanSelection.activeId)
        : undefined) ?? visibleItems[0] ?? null);
  const selectedSourceUrl = selectedItem ? safeExternalUrl(selectedItem.source_url) : null;

  function toggleChecked(pk: number, checked: boolean) {
    const currentlyChecked = orderPlanSelection.selectedIdSet.has(pk);
    if (checked !== currentlyChecked) orderPlanSelection.toggle(pk);
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

  const feedbackHistoryQuery = useQuery({
    queryKey: ["order-plan-c2", "feedback-history", selectedItem?.order_plan_pk, latestExecution?.execution_id],
    queryFn: ({ signal }) => api.getOrderPlanScreeningFeedback(
      selectedItem?.order_plan_pk as number,
      latestExecution?.execution_id,
      { signal },
    ),
    enabled: dialog === "feedback" && Boolean(selectedItem) && Boolean(latestExecution),
    staleTime: 15_000,
  });

  /**
   * A deep link owns its target. If an existing filter hides it, clear that
   * filter and move to the target's page so the selected row and pane agree.
   * Once initialized, ordinary filtering resumes and may hide the current row.
   */
  useEffect(() => {
    if (!isExplicitDeepLink || selectedPk === null || deepLinkPending || deepLinkFailed || !explicitTargetItem) return;
    const defaultViewCandidate = Boolean(latestExecution) && !AXIS_KEYS.some((key) => searchParams.has(key));
    const defaultAxes: AxisSelection = {
      qwenSet: new Set<RelevanceToken>(["relevant", "uncertain"]),
      stage1Set: new Set<Stage1Token>(),
      feedbackSet: new Set<FeedbackToken>(),
      issueOn: false,
    };
    const hiddenByCurrentFilters = !explicitTargetInFilteredItems;
    const hiddenByDefaultView = defaultViewCandidate && !matchesAxes(explicitTargetItem, defaultAxes);
    const targetHidden = hiddenByCurrentFilters || hiddenByDefaultView;
    // Keep a valid target's current filter context when it is already visible.
    // Only use the complete collection after deciding that a filter hid it.
    const targetCollection = targetHidden ? sortByRelevance(allItems) : filteredItems;
    const targetIndex = targetCollection.findIndex((item) => item.order_plan_pk === selectedPk);
    const targetOffset = targetIndex < 0 ? 0 : Math.floor(targetIndex / PAGE_SIZE) * PAGE_SIZE;
    const targetOutsideVisiblePage = targetIndex >= 0 && (targetIndex < offset || targetIndex >= offset + PAGE_SIZE);
    if (targetHidden || targetOutsideVisiblePage) {
      const params = new URLSearchParams(searchParams);
      if (targetHidden) {
        for (const key of AXIS_KEYS) params.delete(key);
        // An empty axis is the explicit "all" sentinel. Removing every axis
        // would reactivate the normal default review view immediately after the
        // deep-link state is consumed.
        params.set("qwen", "");
      }
      // Keep the deep-link source and selected PK. If the target is beyond the
      // current page, retain the useful page context by selecting its page.
      if (targetOffset > 0) params.set("offset", String(targetOffset));
      else params.delete("offset");
      setSearchParams(params, { replace: true });
      return;
    }
    setDeepLinkActive(false);
  }, [allItems, deepLinkFailed, deepLinkPending, explicitTargetInFilteredItems, explicitTargetItem, isExplicitDeepLink, latestExecution, offset, searchParams, selectedPk, setSearchParams]);

  useEffect(() => {
    if (!visibleItems.length || isExplicitDeepLink || invalidSelectedParam || !orderPlanSelection.hydrated) return;
    const currentActivePk = selectedPk ?? orderPlanSelection.activeId;
    const stillValid = currentActivePk !== null && filteredItems.some((item) => item.order_plan_pk === currentActivePk);
    if (stillValid) return;
    const params = new URLSearchParams(searchParams);
    params.set("selected", String(visibleItems[0].order_plan_pk));
    setSearchParams(params, { replace: true });
    orderPlanSelection.setActiveId(visibleItems[0].order_plan_pk);
  }, [filteredItems, invalidSelectedParam, isExplicitDeepLink, orderPlanSelection, searchParams, selectedPk, setSearchParams, visibleItems]);

  useEffect(() => {
    if (!orderPlanSelection.hydrated || !selectedItem || isExplicitDeepLink) return;
    if (orderPlanSelection.activeId !== selectedItem.order_plan_pk) {
      orderPlanSelection.setActiveId(selectedItem.order_plan_pk);
    }
  }, [isExplicitDeepLink, orderPlanSelection, selectedItem]);

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

  /**
   * 다음 건으로 이동한다. 마지막 건이면 **이동하지 않았다**는 사실을 함께 돌려준다.
   *
   * 이동 여부를 감추면 마지막 건에서도 "다음 발주계획으로 이동합니다"라는 거짓 안내가
   * 남고, 행이 바뀌지 않으니 사유를 비우는 효과도 돌지 않는다.
   */
  function advanceToNext(): { pk: number; moved: boolean } | null {
    if (!selectedItem) return null;
    const idx = filteredItems.findIndex((item) => item.order_plan_pk === selectedItem.order_plan_pk);
    if (idx === -1 || idx + 1 >= filteredItems.length) return { pk: selectedItem.order_plan_pk, moved: false };
    const nextItem = filteredItems[idx + 1];
    const params = new URLSearchParams(searchParams);
    params.set("selected", String(nextItem.order_plan_pk));
    if (idx + 1 >= offset + PAGE_SIZE) params.set("offset", String(offset + PAGE_SIZE));
    setSearchParams(params, { replace: true });
    return { pk: nextItem.order_plan_pk, moved: true };
  }

  /**
   * `advanceToNext`의 반대 방향. ↑가 페이지 첫 행을 넘어가면 앞 페이지의 마지막 행으로
   * 간다. 첫 건에서는 이동하지 않았다는 사실을 그대로 돌려준다.
   */
  function retreatToPrevious(): { pk: number; moved: boolean } | null {
    if (!selectedItem) return null;
    const idx = filteredItems.findIndex((item) => item.order_plan_pk === selectedItem.order_plan_pk);
    if (idx <= 0) return { pk: selectedItem.order_plan_pk, moved: false };
    const previousItem = filteredItems[idx - 1];
    const params = new URLSearchParams(searchParams);
    params.set("selected", String(previousItem.order_plan_pk));
    if (idx - 1 < offset) params.set("offset", String(Math.max(0, offset - PAGE_SIZE)));
    setSearchParams(params, { replace: true });
    return { pk: previousItem.order_plan_pk, moved: true };
  }

  const expectedRevision = selectedItem?.human_feedback?.revision ?? 0;

  const mutation = useMutation({
    mutationFn: () => api.createOrderPlanScreeningFeedback(
      (selectedItem as OrderPlanListItem).order_plan_pk,
      {
        schema_version: "feedback-create-request.v1",
        producer: "human-review-client",
        consumer: "review-api",
        request_id: generateRequestId(),
        execution_id: (latestExecution as OrderPlanScreeningExecutionSummary).execution_id,
        relevance,
        priority: priority || null,
        memo: memo.trim() || null,
        expected_revision: expectedRevision,
      },
      actorName,
    ),
    onSuccess: async () => {
      setSavedMessage("사람 피드백 수정본을 저장했습니다. 추적 상태는 바뀌지 않았습니다.");
      // 저장한 값이 새 기준이 된다. 화면의 입력은 그대로 두고 "저장되지 않은 입력"만 푼다.
      setFeedbackBaseline({ relevance, priority, memo });
      await queryClient.invalidateQueries({ queryKey: ["order-plan-c2", "list"] });
      await queryClient.invalidateQueries({ queryKey: ["order-plan-c2", "feedback-history"] });
    },
  });

  const ready = !bulkPending && Boolean(selectedItem) && Boolean(latestExecution) && actorName.trim().length > 0;
  const decisionDisabledReason = !latestExecution ? "게시된 선별 결과가 있어야 모델 판단에 대한 수정본을 저장할 수 있습니다." : !actorName.trim() ? "담당자 이름을 입력하면 저장할 수 있습니다." : undefined;

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

  const trackingMutation = useMutation({
    mutationFn: (status: Exclude<OpportunityTrackingStatus, "미선택">) => {
      const tracking = selectedItem?.tracking;
      if (!tracking) throw new Error("추적 결정을 기록할 소유 사업기회가 없습니다.");
      return api.updateOpportunityTrackingStatus(
        tracking.opportunity_id,
        { tracking_status: status, reason: trackingReason },
        trackingActor,
      );
    },
    onSuccess: async (saved) => {
      // 방금 저장에 성공한 사유를 비우기 **전에** 잡아 둔다. 이것이 다음 건의
      // `직전 사유 다시 쓰기` 후보이고, 드롭다운을 미리 채우는 것과는 다르다.
      if (trackingReason) {
        setLastReason(trackingReason);
        saveSessionValue(LAST_REASON_STORAGE_KEY, trackingReason);
      }
      // 사유는 건마다 다시 고르는 값이므로 저장에 성공하면 **언제나** 비운다. 다음 건으로
      // 옮겨 가는 경우는 행 전환 effect도 비우지만, 마지막 건은 행이 바뀌지 않아 여기서
      // 비우지 않으면 방금 저장한 사유가 남고 "저장되지 않은 입력"으로도 계속 잡힌다.
      setReasonChoice("");
      setCustomReason("");
      await queryClient.invalidateQueries({ queryKey: ["order-plan-c2", "list"] });
      const next = advanceToNext();
      if (next) {
        setTrackingMessage({
          pk: next.pk,
          text: next.moved
            ? `추적 상태를 ${saved.tracking_status}(으)로 기록했습니다. 다음 발주계획으로 이동합니다.`
            : `추적 상태를 ${saved.tracking_status}(으)로 기록했습니다. 현재 목록의 마지막 발주계획이라 이동하지 않습니다.`,
        });
      }
    },
  });

  const trackingDisabledReason = bulkPending
    ? "일괄 추적 저장 요청이 끝날 때까지 단건 추적 입력과 저장을 잠급니다."
    : trackingAvailabilityState === "contract_missing"
    ? "추적 결정을 저장할 서버 계약이 아직 구현되지 않았습니다."
    : trackingAvailabilityState === "opportunity_missing"
      ? "이 발주계획을 소유한 사업기회를 확인하지 못해 추적 결정을 기록할 수 없습니다."
      : !trackingReason && !trackingActor.trim()
        ? "선택 사유와 담당자 이름을 입력하면 추적 결정을 기록할 수 있습니다."
        : !trackingReason
          ? (reasonChoice === OTHER_REASON
            ? "선택 사유를 직접 입력하면 추적 결정을 기록할 수 있습니다."
            : "선택 사유를 고르면 추적 결정을 기록할 수 있습니다.")
          : !trackingActor.trim()
            ? "담당자 이름을 입력하면 추적 결정을 기록할 수 있습니다."
            : trackingMutation.isPending
              ? "추적 결정 저장 요청을 처리하고 있습니다."
              : undefined;
  const trackingReady = !bulkPending && Boolean(selectedItem) && trackingDisabledReason === undefined;

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
    if (!trackingReady) return;
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
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedItem?.order_plan_pk]);

  /** 저장하지 않는다. 상태를 미선택에 그대로 두고 다음 건으로만 이동한다(요청안 §4). */
  function skipCurrent() {
    withRowGuard(() => {
      trackingMutation.reset();
      const next = advanceToNext();
      if (next) {
        setTrackingMessage({
          pk: next.pk,
          text: next.moved
            ? "추적 상태를 바꾸지 않고 다음 발주계획으로 이동했습니다. 미선택은 추적 종료가 아닙니다."
            : "추적 상태를 바꾸지 않았습니다. 현재 목록의 마지막 발주계획이라 이동하지 않습니다. 미선택은 추적 종료가 아닙니다.",
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
        if (direction === "next") advanceToNext();
        else retreatToPrevious();
      });
    },
    onSelect: selectRow,
    selectedKey: selectedItem?.order_plan_pk ?? null,
  });

  /** 담당자 이름은 감사 표식이므로 이 탭에서만 기억한다(인증도, 계정도 아니다). */
  function changeTrackingActor(value: string) {
    setTrackingActor(value);
    saveSessionValue(TRACKING_ACTOR_STORAGE_KEY, value);
  }

  /** 직전 사유를 지금 건에 다시 쓴다. preset에 없는 문장은 `기타`의 자유 입력으로 들어간다. */
  function reuseLastReason() {
    if (!lastReason) return;
    if ((TRACKING_REASONS as readonly string[]).includes(lastReason)) {
      setReasonChoice(lastReason);
      return;
    }
    setReasonChoice(OTHER_REASON);
    setCustomReason(lastReason);
  }

  /**
   * 목록 행에서 Ctrl/Cmd+Enter로 `추적 시작`.
   *
   * 준비가 안 됐으면 **아무것도 채우지 않고** 무엇이 필요한지 말한 뒤 사유 드롭다운으로
   * 초점을 옮긴다. 한 키가 사유를 지어내면 감사 기록이 사람의 판단이 아니게 된다.
   */
  function handleRowKeyDown(event: ReactKeyboardEvent<HTMLElement>, pk: number) {
    if (bulkPending) return;
    if (!(event.ctrlKey || event.metaKey) || event.key !== "Enter") return;
    // 초점이 있는 행과 결정이 붙어 있는 건이 다르면(이탈 확인을 취소한 직후) 결정하지 않는다.
    if (pk !== selectedItem?.order_plan_pk) return;
    // DenseListRow의 Enter→선택보다 먼저다. hook의 ↑↓도 defaultPrevented를 보고 비켜난다.
    event.preventDefault();
    if (trackingReady) {
      decideTracking("계속 추적");
      return;
    }
    setTrackingMessage({ pk, text: "사유와 담당자를 입력하면 Ctrl+Enter로 추적을 시작합니다." });
    trackingSectionRef.current?.querySelector<HTMLElement>('[role="combobox"]')?.focus();
  }

  /** 비율 기본값일 때의 실제 px. 화살표 조작과 aria 값이 읽을 현재 폭이다. */
  const effectiveListWidth = listWidth ?? measuredListWidth;

  function updateListWidth(next: number) {
    const clamped = Math.min(MAX_LIST_WIDTH, Math.max(MIN_LIST_WIDTH, Math.round(next)));
    setListWidth(clamped);
    saveListWidth(clamped);
  }

  // 비율 기본값에서도 aria-valuenow 가 실제 폭을 말해야 한다. 창 크기가 바뀌면 같이 바뀐다.
  useEffect(() => {
    const pane = listPaneRef.current;
    if (!pane || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(([entry]) => {
      setMeasuredListWidth(Math.round(entry.contentRect.width));
    });
    observer.observe(pane);
    return () => observer.disconnect();
  }, [Boolean(sourceRunId), listQuery.isPending, listQuery.isError]);

  useEffect(() => {
    function onMove(event: MouseEvent) {
      const dragState = dragStateRef.current;
      if (!dragState) return;
      const delta = (event.clientX - dragState.startX) / dragState.renderedScale;
      updateListWidth(dragState.startWidth + delta);
    }
    function onUp() {
      dragStateRef.current = null;
    }
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // 오류 문구는 화면마다 따로 만들지 않는다. 서버 raw message를 그대로 싣지
  // 않고 `describeApiError`가 옮긴 문장만 쓴다.
  const listError = describeApiError(listQuery.error, "발주계획 목록을 확인할 수 없습니다.").title;
  const executionError = describeApiError(executionsQuery.error, "C-2 실행 목록을 확인할 수 없습니다.").title;
  const hasProblem = executionsQuery.isPending || executionHasProblem(latestExecution, scopedExecutions);
  // 목록 머리글이 "무엇을 보고 있는가"를 문장으로 밝힌다. 축 안은 OR, 축끼리는 AND다.
  const filterMeaning = (() => {
    if (isDefaultView) return "기본 보기 · BM25 선정 AND 모델 판단 관련·불확실";
    const parts: string[] = [];
    if (stage1Set.size) parts.push(`BM25 ${Array.from(stage1Set).join("·")}`);
    if (qwenSet.size) parts.push(`모델 판단 ${Array.from(qwenSet).join("·")}`);
    if (feedbackSet.size) parts.push(`사람 판단 ${Array.from(feedbackSet).map((token) => (token === "has" ? "있음" : "없음")).join("·")}`);
    if (issueOn) parts.push("실패·거부만");
    if (qText.trim()) parts.push(`검색 "${qText.trim()}"`);
    return parts.length ? parts.join(" AND ") : "전체";
  })();

  const activeFilterCount = isDefaultView
    ? 0
    : qwenSet.size + stage1Set.size + feedbackSet.size + (issueOn ? 1 : 0) + (qText.trim() ? 1 : 0);

  const selectedIndex = selectedItem
    ? filteredItems.findIndex((item) => item.order_plan_pk === selectedItem.order_plan_pk) + 1
    : 0;
  const feedbackSummaryLabel = selectedItem?.human_feedback
    ? `${selectedItem.human_feedback.relevance} · 우선순위 ${selectedItem.human_feedback.priority ?? "미지정"}`
    : "미입력";

  return (
    <section className="c2l-page" data-astryx-theme="bidops" aria-labelledby="order-plans-title">
      {/* 화면의 시각 제목은 상단바의 `<h1>`이 진다(제목 모드, `route-meta.ts`). 페이지가
          같은 이름을 한 번 더 그리면 세로 공간을 두 번 쓰므로 여기에는 문서 구조와
          `aria-labelledby`를 위한 숨긴 제목만 남긴다. */}
      <h2 className="visually-hidden" id="order-plans-title">발주계획</h2>
      {/* 회차 선택·실행 상태·`실행 상세` 링크는 **이 화면의 상태**를 쓰므로 셸로 올릴 수
          없다. 상단바의 액션 슬롯으로 보낸다(`PageHeaderActions`). */}
      <PageHeaderActions>
        <div className="c2l-header-actions">
          <ReviewFilterSelector className="c2l-run-selector" isDisabled={bulkPending} label="발주계획 수집 회차" clearable={false}
            options={runOptions} value={sourceRunId ?? null} onChange={changeSourceRun}
            placeholder="수집 회차 선택" />
          {/* 실행 상태는 낱말 하나로만 둔다. execution_id·시각·집계는 대화상자가 진다. */}
          <ExecutionStatusChip latest={latestExecution} executions={scopedExecutions} />
          <Button
            label="실행 상태"
            size="sm"
            variant="ghost"
            onClick={() => setDialog("runtime")}
          />
          {bulkRecoveryAvailable && !bulkDialogOpen ? (
            <Button
              label="저장된 일괄 요청 확인"
              size="sm"
              variant="secondary"
              onClick={() => setBulkDialogOpen(true)}
            />
          ) : null}
          {sourceRunId ? (
            <Link className="c2l-scope-link" to={`/run-status?run=${encodeURIComponent(sourceRunId)}`}>
              실행 상세 →
            </Link>
          ) : null}
        </div>
      </PageHeaderActions>

      {executionsQuery.isPending ? <Text type="body" color="secondary" as="p" role="status">C-2 실행 목록을 불러오는 중…</Text> : null}
      {executionsQuery.isError ? (
        <Banner status="error" title="C-2 실행 목록을 불러오지 못했습니다." description={executionError} collapsible={false}
          endContent={<Button label="다시 시도" size="sm" onClick={() => void executionsQuery.refetch()} />} />
      ) : null}

      {runsQuery.isError ? <Banner status="error" title="수집 회차 목록을 불러오지 못했습니다."
        description={describeApiError(runsQuery.error, "수집 회차를 확인할 수 없습니다.").title}
        collapsible={false} endContent={<Button label="회차 다시 조회" onClick={() => void runsQuery.refetch()} />} /> : null}
      {runsQuery.isPending ? <Text as="p" role="status">수집 회차를 불러오는 중…</Text> : null}
      {!executionsQuery.isPending && !executionsQuery.isError && !latestExecution ? (
        sourceRunId ? <Banner status="info" title="선별 전 · 수집 데이터 조회"
          description="이 회차에 게시된 선별 결과가 없습니다. 원본 발주계획을 조회하며 모델 판단은 값 없음으로 표시합니다." collapsible={false} />
          : <ExecutionMissingBlock executions={scopedExecutions} />
      ) : null}

      {isExplicitDeepLink && invalidSelectedParam ? (
        <Banner status="error" title="발주계획 식별자가 올바르지 않습니다."
          description="요청한 발주계획을 선택하지 못했습니다. 목록의 행을 직접 선택하십시오." collapsible={false} />
      ) : null}
      {isExplicitDeepLink && deepLinkNeedsSource && deepLinkPlanQuery.isPending ? (
        <Text type="body" color="secondary" as="p" role="status">선택한 발주계획의 수집 회차를 확인하는 중…</Text>
      ) : null}
      {isExplicitDeepLink && deepLinkNeedsSource && deepLinkPlanQuery.isError ? (
        <Banner status="error" title="요청한 발주계획을 찾을 수 없습니다."
          description={describeApiError(deepLinkPlanQuery.error, "발주계획을 확인할 수 없습니다.").detail} collapsible={false} />
      ) : null}
      {isExplicitDeepLink && deepLinkNeedsSource && deepLinkPlanQuery.data && !deepLinkSourceRunId ? (
        <Banner status="error" title="발주계획의 수집 회차를 확인할 수 없습니다."
          description="관측 회차가 없어 목록의 다른 발주계획으로 바꾸지 않았습니다." collapsible={false} />
      ) : null}

      {sourceRunId ? (
        <WorkspaceFrame>
          {/* 탐색과 추적 4화면이 같은 필터 골격을 쓴다(`WorkspaceFilters`). 보기 탭과
              검색만 늘 보이고, 기술 축은 `상세 필터` 뒤에 접어 둔다. 접어도 URL 동기화와
              축의 AND/OR 의미는 그대로이며, 접힌 채로 걸려 있는 필터 수를 토글이 말한다. */}
          <WorkspaceFilterBar
            activeFilterCount={activeFilterCount}
            aria-label="C-2 결과 필터"
            className="c2l-filters"
          >
            <WorkspaceFilterLine>
              {/* 건수는 서버가 아니라 이미 불러온 회차 전체에서 센다. 목록 자체가
                  클라이언트에서 좁혀지므로 같은 규칙(`matchesAxes`)을 두 번 쓰지 않는다. */}
              <WorkspaceViewTabs
                label="보기"
                onChange={applyPreset}
                tabs={PRESETS.map((preset) => ({
                  key: preset.key,
                  label: preset.label,
                  count: presetCounts.get(preset.key) ?? null,
                }))}
                value={activePreset ?? ""}
              />
              <WorkspaceFilterEnd>
                <WorkspaceSearch
                  isDisabled={bulkPending}
                  label="사업명·발주기관·계획번호 검색"
                  onChange={setSearchText}
                  onEnter={() => changeAxes({ q: searchText })}
                  placeholder="사업명·발주기관 검색"
                  value={searchText}
                />
                <WorkspaceAdvancedToggle
                  activeCount={activeFilterCount}
                  controlsId="c2l-advanced-filters"
                  isOpen={advancedOpen}
                  onToggle={() => setAdvancedOpen((open) => !open)}
                />
              </WorkspaceFilterEnd>
            </WorkspaceFilterLine>

            {advancedOpen ? (
              <WorkspaceFilterAdvanced columns={4} id="c2l-advanced-filters" onReset={resetFilters}>
                <div className="c2l-filter-axis">
                  <Text type="label" color="secondary" as="p">Qwen relevance</Text>
                  <ToggleButtonGroup
                    type="multiple"
                    label="Qwen relevance 필터"
                    value={Array.from(qwenSet)}
                    onChange={(value) => changeAxes({ qwen: new Set(value as RelevanceToken[]) })}
                  >
                    <ToggleButton value="relevant" label="relevant" />
                    <ToggleButton value="uncertain" label="uncertain" />
                    <ToggleButton value="not_relevant" label="not_relevant" />
                    <ToggleButton value="null" label="null · 값 없음" />
                  </ToggleButtonGroup>
                </div>

                <div className="c2l-filter-axis">
                  <Text type="label" color="secondary" as="p">BM25 stage1</Text>
                  <ToggleButtonGroup
                    type="multiple"
                    label="BM25 stage1 필터"
                    value={Array.from(stage1Set)}
                    onChange={(value) => changeAxes({ stage1: new Set(value as Stage1Token[]) })}
                  >
                    <ToggleButton value="selected" label="selected" />
                    <ToggleButton value="filtered_out" label="filtered_out" />
                    <ToggleButton value="failed" label="failed" />
                    <ToggleButton value="rejected" label="rejected" />
                    <ToggleButton value="null" label="null · 값 없음" />
                  </ToggleButtonGroup>
                </div>

                <div className="c2l-filter-axis">
                  <Text type="label" color="secondary" as="p">사람 피드백</Text>
                  <ToggleButtonGroup
                    type="multiple"
                    label="사람 피드백 필터"
                    value={Array.from(feedbackSet)}
                    onChange={(value) => changeAxes({ feedback: new Set(value as FeedbackToken[]) })}
                  >
                    <ToggleButton value="has" label="있음" />
                    <ToggleButton value="none" label="없음" />
                  </ToggleButtonGroup>
                </div>

                <div className="c2l-filter-axis">
                  <Text type="label" color="secondary" as="p">실행 결과</Text>
                  <ToggleButton
                    value="issue"
                    label="실패·거부만"
                    isPressed={issueOn}
                    onPressedChange={(pressed) => changeAxes({ issue: pressed })}
                  />
                </div>

                <div className="c2l-filter-axis c2l-saved-views">
                  <Text type="label" color="secondary" as="p">저장된 뷰</Text>
                  <div className="c2l-saved-views-row">
                    <ReviewFilterSelector
                      clearable={false}
                      label="저장된 뷰"
                      options={savedViews.map((view) => ({ value: view.id, label: view.name }))}
                      value=""
                      onChange={(id) => {
                        const view = savedViews.find((item) => item.id === id);
                        if (view) applySavedViewSearch(view.search);
                      }}
                      placeholder={savedViews.length ? "저장된 뷰 선택" : "저장된 뷰 없음"}
                      isDisabled={savedViews.length === 0}
                    />
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
                          <Button className="c2l-view-delete" label={`${view.name} 삭제`} isIconOnly icon={<span aria-hidden="true">×</span>} size="sm" variant="ghost" onClick={() => deleteSavedView(view.id)} />
                        </li>
                      ))}
                    </ul>
                  ) : null}
                </div>
              </WorkspaceFilterAdvanced>
            ) : null}
          </WorkspaceFilterBar>

          {/* 목록을 불러오는 중이거나 실패해도 두 pane 골격은 그대로 둔다. 화면이 통째로
              접혔다 펴지면 사람이 보던 자리를 잃는다(시안의 loading·failure 상태). */}
          <SplitWorkspace
              aria-label="발주계획 목록과 상세"
              className="c2l-workspace"
              style={{ "--c2l-list-width": listWidth === null ? DEFAULT_LIST_WIDTH : `${listWidth}px` } as React.CSSProperties}
            >
              <aside className="c2l-list-pane" ref={listPaneRef}>
                <header className="c2l-list-head">
                  <div className="c2l-list-head-row">
                    {/* 목록을 못 읽었으면 건수는 0이 아니라 확인 불가다. 실패를 0건으로 적지 않는다. */}
                    <Text type="label" color="primary" as="p">
                      검토 목록 · {listQuery.isError
                        ? "현재 필터 결과 확인 불가"
                        : listQuery.isPending
                          ? "불러오는 중"
                          : `현재 필터 결과 ${total.toLocaleString("ko-KR")}건`}
                    </Text>
                    {listQuery.isPending || listQuery.isError ? null : (
                      <Text type="supporting" color="secondary" as="p">{visibleItems.length ? offset + 1 : 0}–{Math.min(offset + visibleItems.length, total)} / {total.toLocaleString("ko-KR")}</Text>
                    )}
                  </div>
                  <div className="c2l-selection-toolbar" data-testid="order-plan-selection-toolbar">
                    <Text type="supporting" color="secondary" as="span" aria-live="polite">
                      선택 {orderPlanSelection.selectedIds.length.toLocaleString("ko-KR")}건
                    </Text>
                    <span className="visually-hidden" id="c2l-selection-action-reason">
                      {bulkPending
                        ? "일괄 추적 요청을 처리하는 동안 선택을 바꿀 수 없습니다."
                        : mutation.isPending || trackingMutation.isPending
                          ? "기존 저장 요청이 끝날 때까지 일괄 추적을 시작할 수 없습니다."
                        : !orderPlanSelection.hydrated
                          ? "목록 선택 상태를 준비하는 중입니다."
                          : !orderPlanSelection.storageAvailable || orderPlanSelection.storageError
                            ? "선택 저장소를 확인하지 못해 단건 추적 경로를 사용하십시오."
                            : orderPlanSelection.selectedIds.length === 0
                              ? "하나 이상의 발주계획을 선택하십시오."
                              : "선택한 발주계획을 일괄 추적하기 전에 대상과 공통 입력을 확인하십시오."}
                    </span>
                    <Button
                      aria-describedby="c2l-selection-action-reason"
                      label="선택 항목 검토"
                      size="sm"
                      variant="primary"
                      isDisabled={bulkPending || mutation.isPending || trackingMutation.isPending || !orderPlanSelection.hydrated || !orderPlanSelection.storageAvailable || Boolean(orderPlanSelection.storageError) || orderPlanSelection.selectedIds.length === 0}
                      onClick={() => setBulkDialogOpen(true)}
                    />
                    <Button
                      aria-describedby="c2l-selection-action-reason"
                      label="선택 전체 해제"
                      size="sm"
                      variant="ghost"
                      isDisabled={bulkPending || orderPlanSelection.selectedIds.length === 0 || !orderPlanSelection.hydrated}
                      onClick={() => orderPlanSelection.clear()}
                    />
                  </div>
                  {(!orderPlanSelection.storageAvailable || orderPlanSelection.storageError) && orderPlanSelection.hydrated ? (
                    <p className="c2l-selection-storage-warning" role="alert">
                      이 탭의 선택 저장소를 사용할 수 없어 일괄 추적을 사용할 수 없습니다. 단건 추적 경로를 사용하십시오.
                    </p>
                  ) : null}
                  {/* 무엇을 보고 있는지는 한 줄로 남긴다. 축 안은 OR, 축끼리는 AND다. */}
                  <p className="c2l-list-scope" title={filterMeaning}>
                    <Text type="supporting" color="secondary" as="span">{filterMeaning}</Text>
                  </p>
                  <p className="c2l-list-scope c2l-list-sort" title="관련 → 판단 보류 → 비관련 → 값 없음">
                    <Text type="supporting" color="secondary" as="span">정렬 · 관련 → 판단 보류 → 비관련 → 값 없음</Text>
                  </p>
                </header>
                {listQuery.isPending ? (
                  <div className="c2l-list-empty" role="status">
                    <Text type="body" color="secondary" as="p">발주계획을 불러오는 중…</Text>
                  </div>
                ) : listQuery.isError ? (
                  <div className="c2l-list-empty">
                    <ReviewState
                      kind="failure"
                      title="발주계획 목록을 불러오지 못했습니다."
                      description={listError}
                      action={<Button label="다시 시도" size="sm" onClick={() => void listQuery.refetch()} />}
                    />
                  </div>
                ) : visibleItems.length === 0 ? (
                  /* 시안의 빈 상태 패턴. 값이 없다는 사실과 되돌리는 방법을 함께 준다. */
                  <div className="c2l-list-empty">
                    <ReviewState
                      kind="empty"
                      title="조건에 맞는 계획이 없습니다"
                      description="검색어나 필터를 바꿔보세요. 표시되지 않은 값이나 실행 실패를 다른 relevance 상태로 바꾸지 않습니다."
                      action={<Button label="필터 초기화" size="sm" onClick={resetFilters} />}
                    />
                  </div>
                ) : (
                  <DenseList
                    aria-label="발주계획 검토 목록"
                    className="c2l-list-scroll"
                    onKeyDown={rowNavigation.onKeyDown}
                    onPointerDownCapture={rowNavigation.onPointerDownCapture}
                    ref={listRef}
                  >
                    {visibleItems.map((item) => (
                      <OrderPlanRow
                        key={item.order_plan_pk}
                        item={item}
                        isSelected={selectedItem?.order_plan_pk === item.order_plan_pk}
                        isChecked={orderPlanSelection.selectedIdSet.has(item.order_plan_pk)}
                        onCheckedChange={(checked) => toggleChecked(item.order_plan_pk, checked)}
                        disabled={bulkPending}
                        onKeyDown={(event) => handleRowKeyDown(event, item.order_plan_pk)}
                        onSelect={() => selectRow(item.order_plan_pk)}
                        rowProps={rowNavigation.rowProps(item.order_plan_pk)}
                      />
                    ))}
                  </DenseList>
                )}
                {/* 기본 보기가 숨기는 것을 목록 바닥에 밝힌다. 숨김을 부재로 표시하지
                    않는다(PRD §3.2). */}
                {isDefaultView && !listQuery.isPending && !listQuery.isError ? (
                  <p className="c2l-list-foot">
                    <Text type="supporting" color="secondary" as="span">
                      필터 외 BM25 선정 제외·비관련·실패 건은 기본 보기에서 숨김. 없는 것이 아니라 보이지 않는 것입니다.
                    </Text>
                  </p>
                ) : null}
                {hasPrevious || hasNext ? (
                  <nav className="c2l-pager" aria-label="발주계획 목록 페이지">
                    <Button label="이전" size="sm" variant="secondary" isDisabled={!hasPrevious} onClick={() => changeOffset(Math.max(0, offset - PAGE_SIZE))} />
                    <Text type="supporting" color="secondary">{(offset + 1).toLocaleString("ko-KR")}–{Math.min(offset + visibleItems.length, total).toLocaleString("ko-KR")} / {total.toLocaleString("ko-KR")}</Text>
                    <Button label="다음" size="sm" variant="secondary" isDisabled={!hasNext} onClick={() => changeOffset(offset + PAGE_SIZE)} />
                  </nav>
                ) : null}
              </aside>

              <div
                className="c2l-resizer"
                role="separator"
                aria-orientation="vertical"
                aria-label="목록 폭 조절"
                aria-valuemin={MIN_LIST_WIDTH}
                aria-valuemax={MAX_LIST_WIDTH}
                aria-valuenow={effectiveListWidth ?? undefined}
                tabIndex={0}
                onMouseDown={(event) => {
                  if (effectiveListWidth === null) return;
                  const pane = listPaneRef.current;
                  dragStateRef.current = {
                    startX: event.clientX,
                    startWidth: effectiveListWidth,
                    renderedScale: pane ? renderedHorizontalScale(pane) : 1,
                  };
                }}
                onKeyDown={(event) => {
                  const current = effectiveListWidth;
                  if (current === null) return;
                  if (event.key === "ArrowLeft") { updateListWidth(current - LIST_WIDTH_STEP); event.preventDefault(); }
                  else if (event.key === "ArrowRight") { updateListWidth(current + LIST_WIDTH_STEP); event.preventDefault(); }
                  else if (event.key === "Home") { updateListWidth(MIN_LIST_WIDTH); event.preventDefault(); }
                  else if (event.key === "End") { updateListWidth(MAX_LIST_WIDTH); event.preventDefault(); }
                }}
              />

              <section className="c2l-detail-pane">
                {listQuery.isPending || listQuery.isError ? (
                  <div className="c2l-detail-empty">
                    <Text type="body" color="secondary" as="p">
                      {listQuery.isPending ? "목록을 불러온 뒤 상세 정보를 표시합니다." : "목록을 불러오지 못해 상세를 표시할 수 없습니다."}
                    </Text>
                  </div>
                ) : isExplicitDeepLink && deepLinkFailed ? (
                  <div className="c2l-detail-empty">
                    <ReviewState
                      kind="failure"
                      title={invalidSelectedParam ? "발주계획 식별자가 올바르지 않습니다." : "요청한 발주계획을 이 회차에서 찾을 수 없습니다."}
                      description="요청한 대상을 첫 번째 행으로 바꾸지 않았습니다. 회차와 선택한 식별자를 확인하십시오."
                    />
                  </div>
                ) : isExplicitDeepLink && !explicitTargetInFilteredItems ? (
                  <div className="c2l-detail-empty">
                    <Text type="body" color="secondary" as="p">선택한 발주계획을 표시할 수 있도록 필터를 정리하는 중…</Text>
                  </div>
                ) : selectedItem ? (
                  <>
                    {/* 시안 §4: 발주기관을 라벨과 함께 강조 블록으로 먼저 읽히고, 사업명은
                        그다음이다. 식별자와 추적 상태는 한 줄로 붙인다. */}
                    <StickyDecisionHeader className="c2l-detail-head" label="발주계획 상세 헤더">
                      <div className="c2l-agency-feature">
                        <Text type="supporting" color="secondary" as="p" className="c2l-agency-label">발주기관</Text>
                        <Text type="body" color="primary" weight="semibold" as="p" className="c2l-agency-name">{textOrUnknown(selectedItem.agency_name)}</Text>
                      </div>
                      <Heading level={4}>{textOrUnknown(selectedItem.title)}</Heading>
                      <div className="c2l-detail-identity">
                        <Text type="supporting" color="secondary" as="p">발주계획 {selectedItem.order_plan_unty_no} · 계획 ID {selectedItem.order_plan_pk}</Text>
                        <Badge
                          variant={trackingAvailabilityState === "available" ? "neutral" : "warning"}
                          label={trackingStatusLabel(selectedItem)}
                        />
                      </div>
                    </StickyDecisionHeader>
                    <div className="c2l-detail-scroll">
                      <dl className="c2l-detail-facts">
                        <div><dt>발주계획 예산</dt><dd>{budgetValue(selectedItem.budget_amount)}</dd></div>
                        <div><dt>발주 예정</dt><dd>{plannedTiming(selectedItem.planned_order_year, selectedItem.planned_order_month)}</dd></div>
                        <div><dt>사업 분야</dt><dd>{textOrUnknown(selectedItem.business_division)}</dd></div>
                      </dl>

                      {/* 기본 상세는 실제로 있는 근거만 싣는다. 제안요청서 본문·확인할 점은
                          지금 API의 필드가 아니므로 만들어 넣지 않는다. */}
                      <section className="c2l-evidence" aria-labelledby={`c2l-evidence-${selectedItem.order_plan_pk}`}>
                        <div className="c2l-evidence-head">
                          <Heading level={5} id={`c2l-evidence-${selectedItem.order_plan_pk}`}>관련 근거</Heading>
                          <span className="c2l-row-badges">
                            <Badge variant={stage1BadgeVariant(selectedItem.stage1_status)} label={stage1RowLabel(selectedItem.stage1_status)} />
                            <Badge variant={qwenBadgeVariant(selectedItem)} label={qwenRowLabel(selectedItem)} />
                          </span>
                        </div>
                        <p className="c2l-evidence-body">
                          <ReviewValue value={selectedItem.qwen_reason} nullLabel="null (모델 근거 미제공)" />
                        </p>
                        {/* 출처는 서버가 준 값 하나뿐이다. 원문 인용이나 문서 위치를 만들지
                            않고, 어느 알려진 필드를 읽었는지만 이름으로 적는다. */}
                        <dl className="c2l-evidence-source">
                          <dd>{textOrUnknown(selectedItem.title)}</dd>
                          <dt>근거 위치 · 발주계획 사업명</dt>
                        </dl>
                        <p className="c2l-evidence-scope">
                          <Text type="supporting" color="secondary" as="span">
                            계획 정보 기반 탐색 신호 · 회사 적합성과 참여 자격은 미확인
                          </Text>
                        </p>
                      </section>

                      {/* 이 건에 이미 기록된 추적 선택이 있으면 한 줄로 남긴다. 값이 없으면
                          줄 자체를 만들지 않는다. */}
                      {selectedItem.tracking?.tracking_selected_by ? (
                        <p className="c2l-detail-note">
                          <Text type="supporting" color="secondary" as="span">
                            최근 추적 선택 · {selectedItem.tracking.tracking_selected_by} · {formatMoment(selectedItem.tracking.tracking_selected_at)} · 사유 <ReviewValue value={selectedItem.tracking.tracking_reason} nullLabel="null (사유 없음)" />
                          </Text>
                        </p>
                      ) : null}

                      {/* 보조 정보는 기본 동선에서 빼되 지우지 않는다. 같은 자리에서 연다. */}
                      <nav className="c2l-supplementary" aria-label="추가 검토 정보 및 공고 원문">
                        {selectedSourceUrl ? (
                          <Button
                            label="공고 바로가기"
                            size="sm"
                            variant="ghost"
                            href={selectedSourceUrl}
                            target="_blank"
                            rel="noopener noreferrer"
                            tooltip="새 탭에서 발주계획 공고 열기"
                          />
                        ) : (
                          <Text type="supporting" color="secondary" as="span">
                            {selectedItem.source_url ? "공고 URL 확인 불가" : "공고 URL 없음"}
                          </Text>
                        )}
                        <Button
                          aria-label="사람 판단 수정 열기"
                          label={`사람 판단 수정 · ${feedbackSummaryLabel}`}
                          size="sm"
                          variant="ghost"
                          isDisabled={bulkPending}
                          onClick={() => setDialog("feedback")}
                        />
                        <Button
                          aria-label="선별 신호와 실행 기록 열기"
                          label="선별 신호 · 실행 기록"
                          size="sm"
                          variant="ghost"
                          onClick={() => { setSignalTab("signals"); setDialog("signals"); }}
                        />
                      </nav>
                    </div>
                    {/* 분할 화면의 결정 액션은 상세 pane 바닥에 둔다. 여기의 결정은
                        **추적 결정 하나**다(ADR-0046 결정 4). 사람 판단 수정은
                        별도 대화상자가 자기 저장을 소유한다. */}
                    <ReviewDecisionBar
                      className="c2l-detail-actions"
                      // 비활성 사유는 세 결정이 함께 읽는 한 문장이다. 버튼 옆이 아니라
                      // 여기 한 곳에서 그리고, 각 버튼은 같은 id를 `aria-describedby`로 가리킨다.
                      hint={(
                        <>
                          {trackingMutation.isError ? (
                            <span className="c2l-decision-message" role="alert">
                              {describeApiError(trackingMutation.error, "추적 결정을 저장하지 못했습니다.").title} 이 발주계획의 추적 상태는 바뀌지 않았습니다.
                            </span>
                          ) : null}
                          {trackingMessage?.pk === selectedItem.order_plan_pk
                            ? <span className="c2l-decision-message" role="status">{trackingMessage.text}</span>
                            : null}
                          <span className="c2l-decision-hint" id="c2l-tracking-decision-reason">
                            {trackingDisabledReason ?? "선택 후 다음 후보로 이동합니다 · 목록에서 ↑↓ 이동, Ctrl+Enter로 추적 시작 · 최종 입찰 참여 결정과 별개"}
                          </span>
                        </>
                      )}
                      label="발주계획 추적 결정"
                      status={(
                        <TrackingDecisionFields
                          actorName={trackingActor}
                          customReason={customReason}
                          item={selectedItem}
                          lastReason={lastReason}
                          onActorNameChange={changeTrackingActor}
                          onCustomReasonChange={setCustomReason}
                          onReasonChoiceChange={setReasonChoice}
                          onReuseLastReason={reuseLastReason}
                          position={`${selectedIndex} / ${total.toLocaleString("ko-KR")}건`}
                          reasonChoice={reasonChoice}
                          sectionRef={trackingSectionRef}
                          isDisabled={bulkPending}
                        />
                      )}
                      actions={(
                        <>
                          {/* 세 결정이 같은 사유로 함께 막힌다. 첫 액션이 그 문구를
                              한 번만 그리고 나머지는 같은 id를 가리켜, 화면에 같은
                              문장이 세 번 쌓이지 않으면서 각 버튼이 사유를 읽는다. */}
                          <ReviewDecisionAction
                            disabledReasonId="c2l-tracking-decision-reason"
                            isDisabled={bulkPending || !trackingReady}
                            label="추적 시작"
                            variant="primary"
                            onClick={() => decideTracking("계속 추적")}
                          />
                          <ReviewDecisionAction
                            disabledReasonId="c2l-tracking-decision-reason"
                            isDisabled={bulkPending || !trackingReady}
                            label="보류"
                            variant="secondary"
                            onClick={() => decideTracking("보류")}
                          />
                          <ReviewDecisionAction
                            disabledReasonId="c2l-tracking-decision-reason"
                            isDisabled={bulkPending || !trackingReady}
                            label="추적 종료"
                            variant="secondary"
                            onClick={() => decideTracking("종료")}
                          />
                          {/* 아무것도 저장하지 않으므로 계약이 없어도 비활성이 아니다. */}
                          <ReviewDecisionAction
                            label="이번 건 넘기기"
                            variant="ghost"
                            isDisabled={bulkPending}
                            onClick={skipCurrent}
                          />
                        </>
                      )}
                    />
                  </>
                ) : (
                  <div className="c2l-detail-empty">
                    <ReviewState
                      kind="empty"
                      title="조건에 맞는 계획이 없습니다"
                      description="검색어나 필터를 바꿔보세요. 선택한 회차의 원본은 그대로 남아 있습니다."
                      action={<Button label="필터 초기화" size="sm" onClick={resetFilters} />}
                    />
                  </div>
                )}
              </section>
          </SplitWorkspace>
        </WorkspaceFrame>
      ) : null}

      {/* 실행 상태와 표시 규칙. 기본 화면에서 큰 설명 영역을 없앤 대신 여기서 읽는다. */}
      <Dialog isOpen={dialog === "runtime"} onOpenChange={(open) => { if (!open) setDialog(null); }} purpose="info" width={640}>
        <DialogHeader title="실행 상태와 표시 규칙" onOpenChange={() => setDialog(null)} />
        <div className="c2l-dialog-body">
          <ExecutionSummaryLine latest={latestExecution} executions={scopedExecutions} />
          <Text type="body" color="secondary" as="p">
            BM25 후보 신호와 Qwen relevance 신호를 분리해 선택한 회차의 성공/부분 성공 실행을 검토합니다. 이 relevance는 tracking state, fitness grade, readiness, 최종 Go/No-Go가 아닙니다.
          </Text>
          <Text type="supporting" color="secondary" as="p">
            <code>filtered_out</code>는 BM25 탈락, <code>not_relevant</code>는 Qwen relevance, <code>unknown</code>은 정보 부족, <code>null</code>은 값 없음/미적용이며 서로 바꾸지 않습니다.
          </Text>
          {/* 기본 화면의 결정 줄에서 뺀 문장. 뜻은 그대로 남기고 자리만 옮겼다. */}
          <Text type="supporting" color="secondary" as="p">
            미선택은 추적 종료가 아닙니다. 추적 선택은 추적 상태만 기록하며 모델 판단·적합성 등급·참여 준비 상태·최종 Go/No-Go를 바꾸지 않습니다.
          </Text>
          {sourceRunId ? (
            <Text type="supporting" color="secondary" as="p">수집 회차 <span className="c2l-digest">{sourceRunId}</span></Text>
          ) : null}
        </div>
      </Dialog>

      {/* 신호 세부와 실행 기록. 목록 행과 기본 상세에서 뺀 값이 그대로 남아 있다. */}
      <Dialog isOpen={dialog === "signals" && selectedItem !== null} onOpenChange={(open) => { if (!open) setDialog(null); }} purpose="info" width={760}>
        <DialogHeader title="선별 신호와 실행 기록" subtitle={selectedItem ? textOrUnknown(selectedItem.title) : undefined} onOpenChange={() => setDialog(null)} />
        <div className="c2l-dialog-body">
          <TabList value={signalTab} onChange={(value) => setSignalTab(value as SignalTab)} role="tablist" hasDivider>
            <Tab value="signals" label="신호 세부" panelId="c2l-panel-signals" />
            <Tab value="telemetry" label="실행 기록" panelId="c2l-panel-telemetry" />
          </TabList>
          <div id="c2l-panel-signals" role="tabpanel" aria-label="신호 세부" hidden={signalTab !== "signals"}>
            {selectedItem ? <SignalPanel item={selectedItem} /> : null}
          </div>
          <div id="c2l-panel-telemetry" role="tabpanel" aria-label="실행 기록" hidden={signalTab !== "telemetry"}>
            {latestExecution ? <TelemetryPanel
              execution={latestExecution}
              detail={executionDetailQuery.data}
              detailPending={executionDetailQuery.isPending}
              detailError={executionDetailQuery.error}
            /> : <Text as="p">이 회차에 게시된 선별 실행 기록이 없습니다.</Text>}
          </div>
        </div>
      </Dialog>

      {/* 사람 판단 수정. 추적 결정과 다른 요청·다른 저장이며 다음 건으로 이동하지 않는다. */}
      <Dialog isOpen={dialog === "feedback" && selectedItem !== null} onOpenChange={(open) => { if (!open) setDialog(null); }} purpose="form" width={560}>
        <DialogHeader
          title="사람 판단 수정 (선택)"
          subtitle={selectedItem ? textOrUnknown(selectedItem.title) : undefined}
          onOpenChange={() => setDialog(null)}
        />
        <div className="c2l-dialog-body c2l-feedback-dialog">
          <Text type="supporting" color="secondary" as="p">
            기존 사람 판단을 그대로 둡니다. 추적 결정과는 별도 수정본이며 적합성 등급·참여 준비 상태·심층 추적 승인·최종 Go/No-Go를 채우거나 대신하지 않습니다.
          </Text>
          <Badge variant="neutral" label={selectedItem?.human_feedback ? feedbackSummaryLabel : "사람 판단 미입력"} />

          {latestExecution ? (
            feedbackHistoryQuery.isPending ? (
              <Text type="supporting" color="secondary" as="p" role="status">사람 피드백 수정본 이력을 불러오는 중…</Text>
            ) : feedbackHistoryQuery.isError ? (
              <Text type="supporting" color="secondary" as="p" role="alert">사람 피드백 이력을 불러오지 못했습니다. 저장 전 현재 수정본을 확인할 수 없습니다.</Text>
            ) : (
              <ReviewRevisionHistory
                className="c2l-feedback-history"
                empty="사람 피드백이 없습니다. 사람 판단을 새 수정본으로 기록할 수 있습니다."
                entries={(feedbackHistoryQuery.data?.items ?? []).map((item) => ({
                  actor: item.claimed_name,
                  at: formatMoment(item.created_at),
                  body: (
                    <dl>
                      <div><dt>priority</dt><dd>{item.priority ?? "null (미지정)"}</dd></div>
                      <div><dt>note</dt><dd>{item.memo ?? "null (메모 미제공)"}</dd></div>
                      <div><dt>execution</dt><dd className="c2l-digest">{item.execution_id}</dd></div>
                    </dl>
                  ),
                  id: item.feedback_id,
                  revision: item.revision,
                  tags: <Badge variant="neutral" label={item.relevance} />,
                }))}
                headingLevel={5}
                label="사람 피드백 수정본 이력"
              />
            )
          ) : (
            <Text type="supporting" color="secondary" as="p">피드백을 기록할 실행 이력이 없습니다. 실행 기록 없이 수정본을 만들지 않습니다.</Text>
          )}

          <div className="c2l-feedback-field">
            <Text type="label" color="secondary" as="p">relevance</Text>
            <SegmentedControl isDisabled={bulkPending} value={relevance} onChange={(value) => setRelevance(value as OrderPlanRelevance)} label="사람 relevance 판단">
              <SegmentedControlItem value="relevant" label="relevant" />
              <SegmentedControlItem value="uncertain" label="uncertain" />
              <SegmentedControlItem value="not_relevant" label="not_relevant" />
            </SegmentedControl>
          </div>

          <div className="c2l-feedback-field">
            <Text type="label" color="secondary" as="p">priority</Text>
            <SegmentedControl isDisabled={bulkPending} value={priority || "null"} onChange={(value) => setPriority(value === "null" ? "" : (value as OrderPlanFeedbackPriority))} label="사람 priority 판단">
              <SegmentedControlItem value="high" label="high" />
              <SegmentedControlItem value="medium" label="medium" />
              <SegmentedControlItem value="low" label="low" />
              <SegmentedControlItem value="null" label="null · 미지정" />
            </SegmentedControl>
          </div>

          <TextArea
            label="memo"
            value={memo}
            onChange={setMemo}
            rows={3}
            placeholder="사람 검토 근거 또는 다음 확인 사항"
            isDisabled={bulkPending}
          />

          <TextInput
            label="사람 판단 담당자 이름"
            value={actorName}
            onChange={setActorName}
            description="감사 귀속용 이름이며 로그인·신원 인증·권한 부여가 아닙니다."
            isDisabled={bulkPending}
          />

          <div className="c2l-feedback-actions">
            {mutation.isError ? <Text type="body" color="secondary" role="alert">{describeApiError(mutation.error, "사람 피드백을 저장하지 못했습니다.").title}</Text> : null}
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
        title={endConfirm?.title ?? "추적을 종료합니다"}
      />
      <OrderPlanBulkTrackingDialog
        open={bulkDialogOpen}
        selectedIds={orderPlanSelection.selectedIds}
        selectionGeneration={orderPlanSelection.state.selectionGeneration}
        filterFingerprint={selectionFingerprint}
        actorName={trackingActor}
        onClose={() => {
          setBulkDialogOpen(false);
          setBulkRecoveryAvailable(hasPendingOrderPlanBulkTrackingRequest());
        }}
        onApplied={(resolvedIds, generation) => orderPlanSelection.applyResult(resolvedIds, generation)}
        onInvalidate={invalidateBulkQueries}
        onPersistSelection={orderPlanSelection.persist}
        onPendingChange={handleBulkPendingChange}
        storageAvailable={orderPlanSelection.storageAvailable}
        storageError={orderPlanSelection.storageError?.message ?? null}
      />
    </section>
  );
}
