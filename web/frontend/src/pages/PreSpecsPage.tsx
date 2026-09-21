import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate, useSearchParams } from "react-router-dom";
import { Button } from "@astryxdesign/core/Button";
import { DateInput } from "@astryxdesign/core/DateInput";
import type { ISODateString } from "@astryxdesign/core/Calendar";
import { Dialog, DialogHeader } from "@astryxdesign/core/Dialog";
import { Selector } from "@astryxdesign/core/Selector";
import { EmptyState } from "../components/common/EmptyState";
import { PageHeaderActions } from "../components/common/PageHeaderActions";
import { useUnsavedGuard } from "../components/common/useUnsavedGuard";
import { useRowKeyboardNavigation } from "../components/common/useRowKeyboardNavigation";
import { DenseList, ListColumns, ListPager, ReviewFilterSegmentedControl, SelectionToolbar, SplitWorkspace } from "../components/common/ReviewPrimitives";
import {
  formatCount,
  WorkspaceAdvancedToggle,
  WorkspaceFilterAdvanced,
  WorkspaceFilterBar,
  WorkspaceFilterLine,
  WorkspaceFrame,
  WorkspaceFilterTools,
  WorkspaceSearch,
  WorkspaceViewTabs,
} from "../components/common/WorkspaceFilters";
import { updateTrackingProjection } from "../components/pre-specs/TrackingDecisionControl";
import { api } from "../lib/api";
import {
  AUTO_PREPARATION_FILTER_VALUES, DEADLINE_SCOPE_OPTIONS, DEADLINE_STATUS_OPTIONS, DISPLAY_GRADE_FILTER_VALUES,
  SORT_OPTIONS, TRACKING_STATUS_OPTIONS, VIEWS, WORKSPACES,
  originLabel, titleOf, validAutoPreparationStatus, validDeadlineScope, validDeadlineStatus,
  validDisplayGrade, validObservedDate, validOverviewView, validTrackingDecision, validTrackingStatus,
  validWorkspace, workspaceOf, type WorkspaceKey,
} from "../lib/preSpecViews";
import { PRE_SPEC_AUTO_PREPARATION_STATUS_LABEL } from "../lib/preSpecAutoPreparation";
import { ReviewExclusionDialog } from "../components/pre-specs/ReviewExclusionDialog";
import { PreSpecDetail } from "../components/pre-specs/PreSpecListDetailPane";
import { PreSpecRow } from "../components/pre-specs/PreSpecListRow";
import { useListSelection } from "../components/common/useListSelection";
import {
  PRE_SPECS_SELECTION_STORAGE_KEY,
  isPreSpecSelectionSortMetadata,
  preSpecsFilterFingerprint,
  sortPreSpecMetadata,
  type PreSpecSelectionSortMetadata,
} from "../lib/listSelection";
import {
  createPreSpecSelectionReview,
  preSpecDetailUrl,
} from "../lib/preSpecSelectionReview";
import { formatRunRange } from "../lib/format";
import { searchKey } from "../lib/search";
import type {
  PreSpecReviewExclusionStatus,
  PreSpecReviewExclusionResponse,
  PreSpecListResponse,
  PreSpecOrigin,
  PreSpecSort,
  RunSummary,
} from "../lib/types";
import "../styles/pre-specs-relaxed.css";

/**
 * 사전규격 업무 화면 — 승인 시안(`bidops-pre-specs-erp-20260907`)의 ERP 작업 표면.
 *
 * 골격은 발주계획 검토 화면과 같다: 압축 필터 한 덩어리 아래 목록 38% / 상세 62%가
 * 셸 canvas 높이를 채우고, 스크롤은 목록과 상세 본문 안에서만 일어난다. 그래서
 * 상세 바닥의 추적 선택과 다음 작업은 늘 보인다.
 *
 * 이 화면이 정하는 것은 **사람의 추적 선택 하나**다. 개요 권고, 적합성 등급,
 * 참여 준비 상태, 최종 입찰 Go/No-Go는 서로를 대신하지 않는다(CLAUDE.md 강제 게이트).
 * 화면은 서버가 준 값을 옮길 뿐 등급·상태·건수를 다시 계산하지 않는다.
 */

// 한 페이지에 200건. 서버 한도(500) 안이고, 상단 보기로 좁히는 경우가 대부분이라
// 이 크기면 한 화면에서 업무 화면과 목록이 대체로 일치한다. 그래도 전체 건수가
// 페이지 크기를 넘으면 목록 바닥이 전체 집합과 현재 범위를 함께 밝힌다.
const PAGE_SIZE = 200;
const BUSINESS_DIVISIONS = ["일반용역", "기술용역"] as const;
const ORIGINS: PreSpecOrigin[] = ["추적", "신규"];
// 이전 대시보드의 누적 업무 링크는 workspace를 갖지 않는다. 그 링크의
// 의미(필터 결과 전체)를 보존할 때만 legacy scope를 전체 이력으로 연다.
const LEGACY_DASHBOARD_FILTER_KEYS = [
  "auto_preparation_status",
  "tracking_decision",
  "tracking_status",
  "grade",
] as const;

/** 상세 필터 Selector의 "전체"를 나타내는 표식값. URL에는 실리지 않는다. */
const ALL_OPTION = "__all__";

function validDivision(value: string | null): string {
  return value && BUSINESS_DIVISIONS.includes(value as (typeof BUSINESS_DIVISIONS)[number]) ? value : "";
}

function validOrigin(value: string | null): PreSpecOrigin | "" {
  return value && ORIGINS.includes(value as PreSpecOrigin) ? (value as PreSpecOrigin) : "";
}

function validSort(value: string | null): PreSpecSort | "" {
  return value === "deadline" || value === "observed" || value === "published" ? value : "";
}

function readOffset(value: string | null): number {
  const parsed = Number(value ?? "0");
  return Number.isInteger(parsed) && parsed >= 0 ? parsed : 0;
}

function kstDate(value = new Date()): string {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Seoul",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(value);
  const part = (type: string) => parts.find((entry) => entry.type === type)?.value ?? "";
  return `${part("year")}-${part("month")}-${part("day")}`;
}

/** 한국 달력 기준으로 날짜를 이동한다. Date.parse의 브라우저 timezone을 쓰지 않는다. */
function shiftDate(value: string, days: number): string {
  const [year, month, day] = value.split("-").map(Number);
  const date = new Date(Date.UTC(year, month - 1, day));
  date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString().slice(0, 10);
}

function defaultRecentRange(): { from: string; to: string } {
  const to = kstDate();
  return { from: shiftDate(to, -6), to };
}

function sortForWorkspace(workspace: WorkspaceKey): PreSpecSort {
  return workspaceOf(workspace).defaultSort;
}

function dateInputValue(value: string): ISODateString | undefined {
  return value ? value as ISODateString : undefined;
}

function runOptionLabel(run: RunSummary): string {
  return run.window_from && run.window_to
    ? `${formatRunRange(run.run_id, run.window_from, run.window_to)} 수집`
    : `기간 미확인 · 회차 ${run.run_id.slice(0, 8)}…`;
}

function runOptionDescription(run: RunSummary): string {
  return `${run.kind} · ${run.run_id}`;
}

export function PreSpecsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const swOnly = searchParams.get("sw_only") !== "false";
  const businessDivision = validDivision(searchParams.get("business_division"));
  const origin = validOrigin(searchParams.get("origin"));
  const gradeFilter = validDisplayGrade(searchParams.get("display_grade") ?? searchParams.get("grade"));
  const autoPreparationStatus = validAutoPreparationStatus(searchParams.get("auto_preparation_status"));
  const trackingDecision = validTrackingDecision(searchParams.get("tracking_decision"));
  const trackingStatus = validTrackingStatus(searchParams.get("tracking_status"));
  const hasLegacyView = searchParams.has("view");
  const hasLegacyDashboardFilter = !searchParams.has("workspace")
    && LEGACY_DASHBOARD_FILTER_KEYS.some((key) => searchParams.has(key));
  // 기존 링크의 `view`는 새 누적 workspace 계약으로 옮긴다. 이 URL을 다시
  // 저장할 때는 효과에서 `workspace=all&overview_view=...`로 정규화한다.
  const workspace: WorkspaceKey = hasLegacyView || hasLegacyDashboardFilter
    ? "all"
    : validWorkspace(searchParams.get("workspace"));
  const rawExclusion = searchParams.get("review_exclusion");
  const reviewExclusion = workspace === "all" && (rawExclusion === "included" || rawExclusion === "excluded") ? rawExclusion : "all";
  // 마감 구간은 검토할 항목 전용 시야다(ADR-0064 결정 2·6). 다른 보기에 있을
  // 때도 `current`를 싣는다 — `검토할 항목` 탭 건수가 현재 구간 기준이어야
  // 탭을 눌렀을 때 같은 건수의 목록이 나온다.
  const deadlineScope = workspace === "actionable" ? validDeadlineScope(searchParams.get("deadline_scope")) : "current";
  const overviewView = validOverviewView(hasLegacyView ? searchParams.get("view") : searchParams.get("overview_view"));
  const sourceRunId = searchParams.get("source_run_id")?.trim() ?? "";
  const rawObservedFrom = validObservedDate(searchParams.get("observed_from"));
  const rawObservedTo = validObservedDate(searchParams.get("observed_to"));
  const recentDefaults = workspace === "recent" && !rawObservedFrom && !rawObservedTo
    ? defaultRecentRange()
    : null;
  const observedFrom = rawObservedFrom || recentDefaults?.from || "";
  const observedTo = rawObservedTo || recentDefaults?.to || "";
  // 검토할 항목에서는 마감 축을 구간 전환이 소유하고 상세 필터의 `마감 상태`는
  // 숨는다. URL에 남은 값을 그대로 적용하면 **보이지 않는 필터**가 되어
  // `구간=마감 전 + 상태=마감 경과`가 조용히 0건을 만든다. 그래서 여기서 무시한다
  // (`review_exclusion`을 전체 이력 밖에서 무시하는 것과 같은 규칙). 값은 지우지
  // 않는다 — 다른 보기로 돌아가면 그대로 다시 걸린다.
  const deadlineStatus = workspace === "actionable"
    ? ""
    : validDeadlineStatus(searchParams.get("deadline_status"));
  const queryText = searchParams.get("q") ?? "";
  const requestedSort = validSort(searchParams.get("sort"));
  const sort = requestedSort || sortForWorkspace(workspace);
  const offset = readOffset(searchParams.get("offset"));
  const listSearch = searchParams.toString();
  const selectionFingerprint = preSpecsFilterFingerprint({
    reviewExclusion,
    swOnly,
    businessDivision,
    origin,
    grade: gradeFilter,
    autoPreparationStatus,
    trackingDecision,
    trackingStatus,
    workspace,
    overviewView,
    sourceRunId,
    observedFrom,
    observedTo,
    deadlineStatus,
    deadlineScope,
    q: queryText,
  });

  const [exclusionTarget, setExclusionTarget] = useState<{ ids: number[]; status: PreSpecReviewExclusionStatus; generation: number } | null>(null);
  const exclusionLanding = useRef<{ active: number | null; index: number; order: number[]; offset: number } | null>(null);
  const [searchText, setSearchText] = useState(queryText);
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [scopeDialogOpen, setScopeDialogOpen] = useState(false);
  const [selectionMessage, setSelectionMessage] = useState<string | null>(null);
  const [selectedPk, setSelectedPk] = useState<number | null>(null);
  const listRef = useRef<HTMLDivElement | null>(null);
  const scrollRestoredRef = useRef(false);
  const boundaryLandingRef = useRef<{ offset: number; direction: "next" | "previous" } | null>(null);
  // 상세 pane 바닥의 인라인 추적 폼이 `onDirtyChange`로 알려 주는 미저장 입력
  // (사유·담당자). route 이동은 컨트롤이 스스로 막으므로 여기서는 행 전환·필터
  // 변경·상세 이동·페이지 이동만 확인한다(docs/0915_ui-redesign/spec.md §3.3).
  const [trackingFormVersion, setTrackingFormVersion] = useState(0);
  const [trackingDirty, setTrackingDirty] = useState(false);
  const trackingGuard = useUnsavedGuard(trackingDirty, {
    scope: "pathname",
    title: "추적 결정 입력을 저장하지 않고 옮깁니다",
    message: "저장하지 않은 추적 결정 사유와 담당자 이름이 있습니다. 지금 옮기면 사라지며 저장된 추적 상태는 바뀌지 않습니다.",
    confirmLabel: "저장하지 않고 옮기기",
  });
  const selection = useListSelection<number, PreSpecSelectionSortMetadata>({
    storageKey: PRE_SPECS_SELECTION_STORAGE_KEY,
    filterFingerprint: selectionFingerprint,
    hydrationReady: true,
    initial: { listSearch },
    isValidMetadata: isPreSpecSelectionSortMetadata,
  });

  useEffect(() => setSearchText(queryText), [queryText]);
  useEffect(() => {
    if (!searchParams.has("grade")) return;
    const next = new URLSearchParams(searchParams);
    const legacyGrade = validDisplayGrade(next.get("grade"));
    next.delete("grade");
    if (!next.has("display_grade") && legacyGrade) next.set("display_grade", legacyGrade);
    setSearchParams(next, { replace: true });
  }, [searchParams, setSearchParams]);
  useEffect(() => {
    if (!hasLegacyView && !hasLegacyDashboardFilter) return;
    const next = new URLSearchParams(searchParams);
    if (hasLegacyView) {
      next.delete("view");
      next.set("overview_view", overviewView);
    }
    next.set("workspace", "all");
    setSearchParams(next, { replace: true });
  }, [hasLegacyDashboardFilter, hasLegacyView, overviewView, searchParams, setSearchParams]);
  useEffect(() => {
    selection.setListSearch(listSearch);
  }, [listSearch, selection.setListSearch]);

  const runsQuery = useQuery({
    queryKey: ["runs"],
    queryFn: api.getRuns,
    staleTime: 30_000,
  });
  const sourceRuns = useMemo(
    () => (runsQuery.data?.items ?? [])
      .filter((run) => run.kind === "notices" || run.kind === "mixed")
      .sort((left, right) => right.generated_at.localeCompare(left.generated_at)),
    [runsQuery.data],
  );
  const sourceRunOptions = useMemo(() => {
    const selectedRun = sourceRuns.find((run) => run.run_id === sourceRunId);
    return [
      { value: "", label: "모든 수집 회차", description: "관측 이력 전체" },
      ...sourceRuns.map((run) => ({
        value: run.run_id,
        label: runOptionLabel(run),
        description: runOptionDescription(run),
      })),
      ...(sourceRunId && !selectedRun
        ? [{
            value: sourceRunId,
            label: `선택 회차 · ${sourceRunId.slice(0, 8)}…`,
            description: runsQuery.isError ? "회차 목록 조회 실패" : "목록에서 회차를 확인할 수 없음",
          }]
        : []),
    ];
  }, [runsQuery.isError, sourceRunId, sourceRuns]);

  const listQuery = useMemo(
    () => ({
      review_exclusion: reviewExclusion as "all" | PreSpecReviewExclusionStatus,
      // 구간은 actionable 술어의 일부라 다른 보기의 행·건수를 바꾸지 않는다.
      // 그래서 항상 싣고, 서버는 `workspace_counts.actionable`에만 반영한다.
      deadline_scope: deadlineScope,
      sw_only: swOnly,
      business_division: businessDivision || null,
      origin: origin || null,
      auto_preparation_status: autoPreparationStatus || null,
      workspace,
      overview_view: overviewView,
      display_grade: gradeFilter || null,
      tracking_decision: trackingDecision || null,
      tracking_status: trackingStatus || null,
      source_run_id: sourceRunId || null,
      // Keep the implicit recent window out of the wire query. The API owns
      // the Korea-day default and can therefore apply it only to the recent
      // workspace count while the picker still displays the derived range.
      observed_from: rawObservedFrom || null,
      observed_to: rawObservedTo || null,
      deadline_status: deadlineStatus || null,
      q: queryText || null,
      sort,
      limit: PAGE_SIZE,
      offset,
    }),
    [reviewExclusion, autoPreparationStatus, businessDivision, deadlineScope, deadlineStatus, gradeFilter, offset, origin, overviewView, queryText, rawObservedFrom, rawObservedTo, sort, sourceRunId, swOnly, trackingDecision, trackingStatus, workspace],
  );
  const result = useQuery({
    queryKey: ["pre-specs", { ...listQuery, q: searchKey(queryText) }],
    queryFn: ({ signal }) => api.getPreSpecs(listQuery, { signal }),
    // 기본값으로 돌아왔을 때도 sw_only=true 요청을 다시 보내 ADR-0031의 서버 기본
    // projection과 화면 상태가 같은지 확인한다.
    staleTime: 0,
  });
  useEffect(() => {
    if (scrollRestoredRef.current || !selection.hydrated || !result.isSuccess || !listRef.current) return;
    scrollRestoredRef.current = true;
    listRef.current.scrollTop = selection.state.listScrollTop;
  }, [result.isSuccess, selection.hydrated, selection.state.listScrollTop]);

  const loadedItems = useMemo(() => result.data?.items ?? [], [result.data]);
  // 모든 semantic filter는 서버가 페이지 전에 적용한다. 페이지에서 다시
  // 상태·등급·추적을 접으면 `total`과 행이 서로 다른 집합을 가리키게 된다.
  const items = loadedItems;
  const total = result.data?.total ?? 0;
  const workspaceCounts = result.data?.workspace_counts;
  const workspaceCount = (key: WorkspaceKey): number | null => {
    if (!result.isSuccess) return null;
    return workspaceCounts?.[key] ?? (key === workspace ? total : null);
  };
  // 구간 적용 **전** actionable을 둘로 나눈 서버 건수다. 화면은 옮기기만 하고
  // 다시 세지 않는다. 아직 응답이 없으면 `–`이며 0건으로 접지 않는다.
  const deadlineScopeCounts = result.data?.deadline_scope_counts;
  const deadlineScopeCount = (key: "current" | "passed"): number | null => {
    if (!result.isSuccess) return null;
    return deadlineScopeCounts?.[key] ?? null;
  };
  const isDefaultView = workspace === "actionable" && swOnly && !businessDivision && !origin && !gradeFilter && !queryText
    && !autoPreparationStatus && !trackingDecision && !trackingStatus && !sourceRunId
    && !rawObservedFrom && !rawObservedTo && !deadlineStatus && deadlineScope === "current"
    && overviewView === "all" && !requestedSort && sort === "deadline" && offset === 0;

  const itemKeys = useMemo(() => items.map((item) => item.notice_pk), [items]);
  const selectedItem = items.find((item) => item.notice_pk === selectedPk) ?? null;

  // spec §3.4 `전체 선택` — **지금 이 페이지에 그려진 행만** 기존 선택 뒤에
  // 중복 없이 덧붙인다. 검색 결과 전체를 고르는 조작이 아니며, 다른 페이지에서
  // 고른 ID는 그대로 남는다. 정렬 메타데이터는 체크박스 `toggle`과 같은 규칙으로
  // 함께 기록한다 — 없으면 선택 검토 순서를 만들 수 없다.
  const pageFullySelected = items.length > 0
    && items.every((item) => selection.selectedIdSet.has(item.notice_pk));
  const selectCurrentPage = useCallback(() => {
    const metadataById: Record<string, PreSpecSelectionSortMetadata> = {};
    for (const item of items) {
      metadataById[String(item.notice_pk)] = {
        id: item.notice_pk,
        published_at: item.published_at,
        deadline_at: item.deadline_at,
        last_observed_at: item.last_observed_at ?? null,
      };
    }
    selection.selectMany(items.map((item) => item.notice_pk), metadataById);
  }, [items, selection.selectMany]);

  // Every observed row refreshes only its compact ordering keys. Selection is
  // never intersected with the current page, so off-page checks survive.
  useEffect(() => {
    for (const item of loadedItems) {
      selection.setSortMetadata(item.notice_pk, {
        id: item.notice_pk,
        published_at: item.published_at,
        deadline_at: item.deadline_at,
        last_observed_at: item.last_observed_at ?? null,
      });
    }
  }, [loadedItems, selection.setSortMetadata]);

  // 목록이 바뀌어 선택이 사라지면 첫 행을 고른다. 사람이 고르는 중이던 입력은
  // 상세 pane 바닥의 인라인 폼에 있고, 그 확인은 아래 `selectPk`가 맡는다.
  useEffect(() => {
    if (!selection.hydrated) return;
    if (exclusionLanding.current && result.isFetching) return;
    if (exclusionLanding.current && result.isSuccess) {
      if (items.length === 0 && offset > 0) {
        const nextOffset = Math.max(0, Math.floor((total - 1) / PAGE_SIZE) * PAGE_SIZE);
        const nextParams = new URLSearchParams(searchParams);
        if (nextOffset) nextParams.set("offset", String(nextOffset));
        else nextParams.delete("offset");
        setSearchParams(nextParams, { replace: true });
        return;
      }
      const landing = exclusionLanding.current;
      const visible = new Set(items.map((item) => item.notice_pk));
      const next = landing.active !== null && visible.has(landing.active) ? landing.active
        : offset < landing.offset ? items[items.length - 1]?.notice_pk ?? null
        : landing.order.slice(landing.index + 1).find((id) => visible.has(id))
          ?? items.find((item) => !landing.order.includes(item.notice_pk))?.notice_pk
          ?? landing.order.slice(0, landing.index).reverse().find((id) => visible.has(id))
          ?? items[Math.min(Math.max(landing.index, 0), items.length - 1)]?.notice_pk ?? null;
      exclusionLanding.current = null;
      setSelectedPk(next);
      selection.setActiveId(next);
      requestAnimationFrame(() => listRef.current?.querySelector<HTMLElement>(`[data-row-key="${next}"]`)?.focus());
      return;
    }
    if (items.length === 0) {
      if (selectedPk !== null) setSelectedPk(null);
      return;
    }
    const restoredActive = selection.hydrated ? selection.activeId : null;
    const landing = boundaryLandingRef.current;
    const next = landing?.offset === offset
      ? (landing.direction === "previous" ? items[items.length - 1] : items[0]).notice_pk
      : restoredActive !== null && items.some((item) => item.notice_pk === restoredActive)
      ? restoredActive
      : items.some((item) => item.notice_pk === selectedPk)
        ? selectedPk
        : items[0].notice_pk;
    if (landing?.offset === offset) boundaryLandingRef.current = null;
    if (next !== selectedPk) {
      setSelectedPk(next);
      selection.setActiveId(next);
    }
  }, [result.isFetching, result.isSuccess, total, searchParams, setSearchParams, items, offset, selectedPk, selection.activeId, selection.hydrated, selection.setActiveId]);

  const selectPk = useCallback((next: number) => {
    trackingGuard.confirmDiscard(() => {
      setSelectedPk(next);
      selection.setActiveId(next);
    });
  }, [selection.setActiveId, trackingGuard]);

  const selectedReviewIds = useMemo(() => {
    const metadata = selection.selectedIds
      .map((id) => selection.state.selectedSortMetadata[String(id)])
      .filter((entry): entry is PreSpecSelectionSortMetadata => isPreSpecSelectionSortMetadata(entry));
    if (metadata.length !== selection.selectedIds.length) return null;
    try {
      return sortPreSpecMetadata(metadata, sort).map((entry) => entry.id);
    } catch {
      return null;
    }
  }, [selection.selectedIds, selection.state.selectedSortMetadata, sort]);

  const openDetailFromSelection = useCallback((noticePk: number) => {
    const sortedIds = selectedReviewIds;
    if (!selection.selectedIds.includes(noticePk)) {
      navigate(preSpecDetailUrl(noticePk, listSearch));
      return;
    }
    if (!sortedIds) {
      setSelectionMessage("선택한 항목의 게시·마감·관측 시각을 확인할 수 없어 선택 검토를 시작하지 못했습니다.");
      return;
    }
    const durable = selection.persist();
    if (!durable.ok) {
      setSelectionMessage(durable.error?.message ?? "선택 검토 순서를 저장하지 못했습니다.");
      return;
    }
    const created = createPreSpecSelectionReview({
      orderedNoticeIds: sortedIds,
      listSearch,
      filterFingerprint: selectionFingerprint,
      selectionGeneration: selection.state.selectionGeneration,
      entryNoticeId: noticePk,
    });
    if (!created.ok) {
      setSelectionMessage(created.error);
      return;
    }
    setSelectionMessage(null);
    navigate(preSpecDetailUrl(noticePk, listSearch, created.value.reviewId));
  }, [
    listSearch,
    navigate,
    selectedReviewIds,
    selection.persist,
    selection.selectedIds.length,
    selection.state.selectionGeneration,
    selection.state.selectedSortMetadata,
    selectionFingerprint,
  ]);

  // 상세 화면으로 가는 것도 저장하지 않은 입력을 버릴 수 있으므로 같은 확인을 거친다.
  const openDetail = useCallback((noticePk: number) => {
    trackingGuard.confirmDiscard(() => {
      openDetailFromSelection(noticePk);
    });
  }, [openDetailFromSelection, trackingGuard]);

  const reviewSelected = useCallback(() => {
    const sortedIds = selectedReviewIds;
    if (!sortedIds || sortedIds.length === 0) {
      setSelectionMessage("선택한 항목의 게시·마감·관측 시각을 확인할 수 없어 선택 검토를 시작하지 못했습니다.");
      return;
    }
    openDetail(sortedIds[0]);
  }, [openDetail, selectedReviewIds]);

  const rowKeyboard = useRowKeyboardNavigation<number>({
    containerRef: listRef,
    keys: itemKeys,
    selectedKey: selectedPk,
    onSelect: selectPk,
    // 경계에서는 페이지를 넘긴다. 서버 전체가 한 페이지보다 클 때만 움직인다.
    onBoundary: (direction) => {
      if (direction === "next" && offset + PAGE_SIZE < total) {
        const targetOffset = offset + PAGE_SIZE;
        updateSearchParams({ offset: String(targetOffset) }, () => {
          boundaryLandingRef.current = { offset: targetOffset, direction };
        });
      } else if (direction === "previous" && offset > 0) {
        const targetOffset = Math.max(0, offset - PAGE_SIZE);
        updateSearchParams({ offset: targetOffset > 0 ? String(targetOffset) : null }, () => {
          boundaryLandingRef.current = { offset: targetOffset, direction };
        });
      }
    },
  });

  function openExclusion(ids: readonly number[], status: PreSpecReviewExclusionStatus) {
    if (ids.length === 0 || ids.length > 200) return;
    trackingGuard.confirmDiscard(() => {
      setExclusionTarget({ ids: [...ids], status, generation: selection.state.selectionGeneration });
    });
  }

  async function exclusionSaved(response: PreSpecReviewExclusionResponse) {
    const ids = response.items.map((item) => item.notice_id);
    exclusionLanding.current = { offset, active: selectedPk, index: items.findIndex((item) => item.notice_pk === selectedPk), order: itemKeys };
    selection.applyResult(ids, exclusionTarget?.generation);
    setTrackingDirty(false);
    // Remove the discarded tracking draft even when the active row remains visible.
    setTrackingFormVersion((version) => version + 1);
    setExclusionTarget(null);
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["pre-specs"] }),
      ...ids.map((id) => queryClient.invalidateQueries({ queryKey: ["pre-spec-detail", id] })),
    ]);
  }

  function updateSearchParamsUnsafe(changes: Record<string, string | null>) {
    boundaryLandingRef.current = null;
    const next = new URLSearchParams(searchParams);
    // 보기를 옮기면 그 보기 전용 필터는 따라가지 않는다. `검토 포함 여부`는
    // 전체 이력 전용이고 마감 구간은 검토할 항목 전용이다(ADR-0064 결정 6).
    if (Object.prototype.hasOwnProperty.call(changes, "workspace")) {
      next.delete("review_exclusion");
      next.delete("deadline_scope");
    }
    const hadExplicitScope = searchParams.has("workspace") || hasLegacyView || hasLegacyDashboardFilter;
    for (const [key, value] of Object.entries(changes)) {
      if (value === null || value === "") next.delete(key);
      else next.set(key, value);
    }
    // A clean `/pre-specs` URL means the actionable default. Once a person
    // changes a filter, persist that effective scope so the new query key is
    // not mistaken for an old dashboard link on the next render. Legacy links
    // are normalized by the effect above and keep their all-history meaning.
    if (!hadExplicitScope && !Object.prototype.hasOwnProperty.call(changes, "workspace")) {
      next.set("workspace", workspace);
    }
    // 필터가 바뀌면 페이지를 처음으로 돌린다. 좁힌 조건에서 3페이지째를 보여 주는
    // 것은 사람이 요청한 적 없는 상태다. 단, 호출자가 `offset`을 명시적으로 준
    // 경우(키보드 경계 이동)는 그것이 요청된 페이지이므로 지우지 않는다.
    if (!Object.prototype.hasOwnProperty.call(changes, "offset")) next.delete("offset");
    setSearchParams(next, { replace: true });
  }

  function updateSearchParams(
    changes: Record<string, string | null>,
    after?: () => void,
  ) {
    trackingGuard.confirmDiscard(() => {
      updateSearchParamsUnsafe(changes);
      after?.();
    });
  }

  function applySearch(value: string) {
    const next = searchKey(value) ? value : null;
    const changed = searchKey(next) !== searchKey(queryText);
    const run = () => {
      if (changed) updateSearchParamsUnsafe({ q: next });
      else {
        const params = new URLSearchParams(searchParams);
        if (next) params.set("q", next);
        else params.delete("q");
        setSearchParams(params, { replace: true });
      }
      setSearchText(next ?? "");
    };
    if (changed) trackingGuard.confirmDiscard(run);
    else run();
  }

  function restoreDefaults() {
    updateSearchParams({
      sw_only: null,
      business_division: null,
      origin: null,
      grade: null,
      display_grade: null,
      auto_preparation_status: null,
      tracking_decision: null,
      tracking_status: null,
      workspace: null,
      overview_view: null,
      source_run_id: null,
      observed_from: null,
      observed_to: null,
      deadline_status: null,
      deadline_scope: null,
      q: null,
      sort: null,
      view: null,
    }, () => setSearchText(""));
  }

  function showAllPreSpecs() {
    updateSearchParams({ workspace: "all", overview_view: null, sw_only: "false" });
  }

  function changeWorkspace(nextWorkspace: WorkspaceKey) {
    // 관측 날짜는 최근 workspace에서만 암묵적으로 노출된다. 최근에서
    // 빠져나갈 때 명시적으로 고른 날짜까지 함께 지워야 다음 workspace가
    // 이전 recent 범위에 조용히 갇히지 않는다. 다른 workspace에서 직접
    // 날짜를 지정한 경우에는 전역 관측 필터로 보존한다.
    const clearRecentRange = workspace === "recent" && nextWorkspace !== "recent";
    updateSearchParams({
      workspace: nextWorkspace,
      overview_view: overviewView === "all" ? null : overviewView,
      // 탭마다 계약된 기본 정렬(deadline/observed/published)로 돌아간다.
      sort: null,
      ...(clearRecentRange ? { observed_from: null, observed_to: null } : {}),
    });
  }

  function emptyDescription(): string {
    if (searchKey(queryText)) return `적용된 검색어 "${queryText}"와 다른 활성 필터에 맞는 사전규격이 없습니다.`;
    // 구간은 검토할 항목의 시야이지 항목을 없애는 필터가 아니다(ADR-0064 결정 1).
    // 비었으면 다른 구간에 무엇이 남아 있는지 서버 건수로 알린다.
    if (workspace === "actionable" && deadlineScope === "passed") {
      return "마감 경과 구간에 검토할 항목이 없습니다. 마감 전·미확인 구간으로 돌아가십시오.";
    }
    if (workspace === "actionable" && deadlineScope === "current" && (deadlineScopeCounts?.passed ?? 0) > 0) {
      return `마감 전·미확인 구간에는 없습니다. 마감 경과 ${deadlineScopeCounts?.passed}건은 구간 전환으로 볼 수 있습니다.`;
    }
    if (isDefaultView) return "SW 중심 기본 보기에 맞는 항목이 없습니다. 전체 보기는 SW사업대상과 무관한 사전규격까지 명시적으로 요청합니다.";
    if (overviewView !== "all") return `현재 개요 상태 보기와 필터에 맞는 사전규격이 없습니다. 보기를 바꾸거나 조건을 넓혀 보십시오.`;
    if (swOnly) return "SW 중심 기본 보기와 추가 필터가 함께 적용되어 있습니다. 기본값으로 돌아가거나 조건을 조정해 보십시오.";
    if (autoPreparationStatus || trackingDecision || trackingStatus || gradeFilter || sourceRunId || observedFrom || observedTo || deadlineStatus) {
      return "현재 선택한 업무구분·구분·등급·추적·관측·마감 조건에 맞는 누적 데이터가 없습니다.";
    }
    if (businessDivision || origin || queryText) return "현재 선택한 업무구분·구분·검색어 조건에 맞는 누적 데이터가 없습니다.";
    return "누적 수집된 사전규격 데이터가 아직 없습니다.";
  }

  const rangeEnd = Math.min(offset + loadedItems.length, total);
  const activeWorkspace = workspaceOf(workspace);
  const pageCountLabel = (total > loadedItems.length || offset > 0) && loadedItems.length > 0
    ? `전체 ${total}건 중 ${offset + 1}–${rangeEnd}건`
    : `전체 ${total}건`;

  return (
    <section className="pre-specs-page" data-astryx-theme="bidops" aria-labelledby="page-title">
      {/* 화면 제목은 셸 상단바가 그린다(제목 모드). 페이지는 같은 이름을 세로로 한 번
          더 쓰지 않고, `aria-labelledby`가 가리킬 숨긴 제목만 남긴다. 페이지 상태를
          쓰는 액션(`표시 범위`)은 상단바 슬롯으로 portal한다. */}
      <h2 className="visually-hidden" id="page-title">사전규격</h2>
      <PageHeaderActions>
        <div className="pre-specs-header-actions">
          <Button label="표시 범위" size="sm" variant="ghost" onClick={() => setScopeDialogOpen(true)} />
        </div>
      </PageHeaderActions>

      <WorkspaceFrame>
        <WorkspaceFilterBar aria-label="사전규격 필터" className="pre-specs-filters">
          <WorkspaceFilterLine>
            <WorkspaceViewTabs
              className="pre-specs-views"
              label="사전규격 업무 화면"
              onChange={changeWorkspace}
              tabs={WORKSPACES.map((definition) => ({
                key: definition.key,
                label: definition.label,
                count: workspaceCount(definition.key),
              }))}
              value={workspace}
            />
            {/* 범위 스위치는 필터가 아니라 "지금 무엇을 보고 있는가"다. 보기 탭 바로
                옆에 두어 탭 선택과 한눈에 읽히게 한다. 검색은 아래 도구 행에 둔다. */}
            <div className="pre-specs-filter-context-start">
              <label className="pre-specs-switch">
                <input
                  checked={swOnly}
                  type="checkbox"
                  onChange={(event) => updateSearchParams({ sw_only: event.target.checked ? null : "false" })}
                />
                <span>SW 중심 · 추적 예외 포함</span>
              </label>
              <span className="pre-specs-filter-help">
                {swOnly
                  ? "일반·기술용역 / SW사업대상 Y + 추적 예외"
                  : "SW사업대상과 무관한 사전규격까지 조회"}
              </span>
            </div>
          </WorkspaceFilterLine>

          <WorkspaceFilterTools className="pre-specs-filter-tools">
            <WorkspaceAdvancedToggle
              controlsId="pre-specs-advanced-filters"
              isOpen={advancedOpen}
              onToggle={() => setAdvancedOpen((open) => !open)}
            />
            {/* `q`는 서버 질의 인자다. 글자를 칠 때마다 목록을 다시 부르지 않고
                Enter로 적용한다(적용 시점은 데이터 원천이 정한다). */}
            <WorkspaceSearch
              appliedValue={queryText}
              label="사업명·기관명 검색"
              onChange={setSearchText}
              onClear={() => applySearch("")}
              onEnter={() => applySearch(searchText)}
              value={searchText}
            />
            <div className="pre-specs-filter-context-range">
              <Selector
                className="pre-specs-source-run"
                label="수집 회차"
                size="sm"
                hasSearch
                searchPlaceholder="회차 검색"
                emptySearchText="일치하는 수집 회차가 없습니다"
                options={sourceRunOptions}
                onChange={(value) => updateSearchParams({ source_run_id: value || null })}
                placeholder={runsQuery.isPending ? "회차 목록 조회 중" : "모든 수집 회차"}
                value={sourceRunId}
              />
              {workspace === "recent" || rawObservedFrom || rawObservedTo ? (
                <div className="pre-specs-observation-range" aria-label="관측 날짜 범위">
                  <DateInput
                    className="pre-specs-observation-date"
                    label="관측 시작일"
                    size="sm"
                    value={dateInputValue(observedFrom)}
                    onChange={(value) => updateSearchParams({ observed_from: value ?? null })}
                  />
                  <span aria-hidden="true">–</span>
                  <DateInput
                    className="pre-specs-observation-date"
                    label="관측 종료일"
                    size="sm"
                    value={dateInputValue(observedTo)}
                    onChange={(value) => updateSearchParams({ observed_to: value ?? null })}
                  />
                </div>
              ) : null}
            </div>
            {/* 네 번째 칸 — 보기 전용 조회 조건 하나가 온다. 검토할 항목의 마감
                구간과 전체 이력의 검토 포함 여부는 서로 배타적이라 같은 자리를
                나눠 쓴다(ADR-0064 결정 7). 캡션은 별도 요소다 — Astryx
                `SegmentedControl.label`은 aria 전용이라 화면에 뜨지 않는다. */}
            {workspace === "actionable" ? (
              <div className="pre-specs-deadline-scope">
                {/* 접근 이름은 컨트롤의 `label`이 이미 갖는다. 이 캡션은 같은 말을
                    눈으로 읽게 하는 자리이므로 보조기술에는 한 번만 들리게 한다. */}
                <span aria-hidden="true" className="pre-specs-deadline-scope-caption">마감 구간</span>
                <ReviewFilterSegmentedControl
                  className="pre-specs-deadline-scope-control"
                  label="마감 구간"
                  layout="hug"
                  onChange={(value) => updateSearchParams({ deadline_scope: value === "current" ? null : value })}
                  options={DEADLINE_SCOPE_OPTIONS.map((option) => {
                    const count = deadlineScopeCount(option.value);
                    return {
                      value: option.value,
                      label: `${option.label} ${count === null ? "–" : formatCount(count)}`,
                    };
                  })}
                  value={deadlineScope}
                />
              </div>
            ) : null}
            {workspace === "all" ? <Selector label="검토 포함 여부" size="sm"
              options={[{ value: "all", label: "전체" }, { value: "included", label: "검토 포함" }, { value: "excluded", label: "검토 제외" }]}
              value={reviewExclusion} onChange={(value) => updateSearchParams({ review_exclusion: value === "all" ? null : value })} /> : null}
          </WorkspaceFilterTools>

          {advancedOpen ? (
            <WorkspaceFilterAdvanced
              columns={4}
              id="pre-specs-advanced-filters"
              onReset={restoreDefaults}
              resetLabel="기본값으로"
            >
              <Selector
                label="개요 상태"
                size="sm"
                options={VIEWS.map((definition) => ({ value: definition.key, label: definition.label }))}
                value={overviewView}
                onChange={(value) => updateSearchParams({ overview_view: value === "all" ? null : value })}
              />
              <Selector
                label="업무구분"
                size="sm"
                options={[
                  { value: ALL_OPTION, label: "전체" },
                  ...BUSINESS_DIVISIONS.map((value) => ({ value, label: value })),
                ]}
                value={businessDivision || ALL_OPTION}
                onChange={(value) => updateSearchParams({ business_division: value === ALL_OPTION ? null : value })}
              />
              <Selector
                label="발견 구분"
                size="sm"
                options={[
                  { value: ALL_OPTION, label: "전체" },
                  ...ORIGINS.map((value) => ({ value, label: originLabel(value) })),
                ]}
                value={origin || ALL_OPTION}
                onChange={(value) => updateSearchParams({ origin: value === ALL_OPTION ? null : value })}
              />
              <Selector
                label="예비 적합성 등급"
                size="sm"
                options={[
                  { value: ALL_OPTION, label: "전체" },
                  ...DISPLAY_GRADE_FILTER_VALUES.map((value) => ({ value, label: value })),
                ]}
                value={gradeFilter || ALL_OPTION}
                onChange={(value) => updateSearchParams({ display_grade: value === ALL_OPTION ? null : value, grade: null })}
              />
              <Selector
                label="추적 상태"
                size="sm"
                options={[
                  { value: ALL_OPTION, label: "전체" },
                  ...TRACKING_STATUS_OPTIONS.map((value) => ({ value, label: value })),
                ]}
                value={trackingStatus || ALL_OPTION}
                onChange={(value) => updateSearchParams({ tracking_status: value === ALL_OPTION ? null : value })}
              />
              {/* 검토할 항목에서는 같은 축의 컨트롤을 둘 두지 않는다 — 도구 줄의
                  마감 구간과 이 필터가 함께 걸리면 `구간=마감 전 + 상태=마감 경과`
                  같은 모순 조합이 0건을 만든다(ADR-0064 검토한 대안). */}
              {workspace !== "actionable" ? (
                <Selector
                  label="마감 상태"
                  size="sm"
                  options={[
                    { value: ALL_OPTION, label: "전체" },
                    ...DEADLINE_STATUS_OPTIONS.map((option) => ({ value: option.value, label: option.label })),
                  ]}
                  value={deadlineStatus || ALL_OPTION}
                  onChange={(value) => updateSearchParams({ deadline_status: value === ALL_OPTION ? null : value })}
                />
              ) : null}
              {/* 자동 준비는 서버 질의 인자다 — workspace 건수와 같은 전체 집합을 좁힌다. */}
              <Selector
                label="자동 준비 상태"
                size="sm"
                options={[
                  { value: ALL_OPTION, label: "전체" },
                  ...AUTO_PREPARATION_FILTER_VALUES.map((value) => ({
                    value,
                    label: PRE_SPEC_AUTO_PREPARATION_STATUS_LABEL[value],
                  })),
                ]}
                value={autoPreparationStatus || ALL_OPTION}
                onChange={(value) => updateSearchParams({ auto_preparation_status: value === ALL_OPTION ? null : value })}
              />
              <Selector
                label="추적 결정"
                size="sm"
                options={[
                  { value: ALL_OPTION, label: "전체" },
                  { value: "pending", label: "추적 결정 대기" },
                ]}
                value={trackingDecision || ALL_OPTION}
                onChange={(value) => updateSearchParams({ tracking_decision: value === ALL_OPTION ? null : value })}
              />
              <Selector
                label="표시 순서"
                size="sm"
                options={SORT_OPTIONS.map(({ value, label }) => ({ value, label }))}
                value={sort}
                onChange={(value) => updateSearchParams({ sort: value === sortForWorkspace(workspace) ? null : value })}
              />
            </WorkspaceFilterAdvanced>
          ) : null}
        </WorkspaceFilterBar>

        {/* 조회 중이거나 실패해도 좌우 분할 골격은 그대로 두고 상태를 목록 pane 안에
            그린다(ADR-0062: 발주계획 방식). 화면이 통째로 접혔다 펴지면 사람이 보던
            자리를 잃는다. */}
        <SplitWorkspace className="pre-specs-split-workspace">
            <section className="review-split-list pre-specs-list-pane" aria-label="사전규격 목록">
              <header className="review-list-head pre-specs-list-head">
                <strong>
                  사전규격 목록 <span className="mono tabular-nums">{total}</span>건
                </strong>
                <span>{activeWorkspace.description} · {SORT_OPTIONS.find((option) => option.value === sort)?.label}</span>
              </header>
              <SelectionToolbar
                className="pre-specs-selection-toolbar"
                count={selection.selectedIds.length}
                countClassName="pre-specs-selection-count"
                label="사전규격 선택 작업"
                reasonClassName="pre-specs-selection-disabled-reason"
                reasonId="pre-specs-selection-disabled"
                reason={!selection.hydrationReady
                  ? "선택 저장소를 준비하는 중입니다."
                  : !selection.storageAvailable
                    ? "이 탭의 선택 저장소를 사용할 수 없어 검토 순서를 저장할 수 없습니다."
                  : selection.selectedIds.length === 0
                    ? "선택한 항목이 없습니다."
                    : !selectedReviewIds
                      ? "선택 항목의 정렬 시각을 확인할 수 없습니다."
                      : ""}
                end={(
                  /* `전체 선택`의 범위를 글자로 밝힌다 — 이 단추는 검색 결과 전체가
                     아니라 지금 보이는 페이지만 더한다(spec §3.4). */
                  <span className="pre-specs-selection-page-note">이 페이지만 추가</span>
                )}
                actions={(
                  <>
                    <button
                      className="interaction-control"
                      type="button"
                      onClick={selectCurrentPage}
                      disabled={items.length === 0 || pageFullySelected}
                      aria-label="현재 페이지 전체 선택"
                    >
                      전체 선택
                    </button>
                    <button
                      className="interaction-control"
                      type="button"
                      onClick={() => selection.clear()}
                      disabled={selection.selectedIds.length === 0}
                      aria-label="선택 전체 해제"
                      aria-describedby={selection.selectedIds.length === 0 ? "pre-specs-selection-disabled" : undefined}
                    >
                      전체 해제
                    </button>
                    <Button size="sm" variant="secondary" label="선택 항목 제외"
                      isDisabled={!selection.hydrationReady || !selection.storageAvailable || selection.selectedIds.length === 0 || selection.selectedIds.length > 200}
                      onClick={() => openExclusion(selection.selectedIds, "excluded")} />
                    <button
                      className="interaction-control interaction-control-primary"
                      type="button"
                      onClick={reviewSelected}
                      disabled={!selection.hydrationReady || !selection.storageAvailable || selection.selectedIds.length === 0 || !selectedReviewIds}
                      aria-label="선택 항목 검토"
                      aria-describedby="pre-specs-selection-disabled"
                    >
                      선택 항목 검토
                    </button>
                  </>
                )}
              />
              {selection.selectedIds.length > 200 ? <p role="alert">한 번에 200건까지 제외할 수 있습니다. 선택을 줄여 주세요.</p> : null}
              {selectionMessage ? <p className="pre-specs-selection-message" role="alert">{selectionMessage}</p> : null}
              <ListColumns className="pre-specs-list-columns">
                <span>사업명 / 발주기관</span>
                <span>의견 마감</span>
              </ListColumns>
              <div
                className="pre-specs-list-scroll"
                ref={listRef}
                onScroll={(event) => selection.setListScrollTop(event.currentTarget.scrollTop)}
                onKeyDown={rowKeyboard.onKeyDown}
                onPointerDownCapture={rowKeyboard.onPointerDownCapture}
              >
                {result.isPending ? (
                  <div className="pre-specs-loading" role="status" aria-live="polite">사전규격 목록을 불러오는 중입니다.</div>
                ) : result.isError ? (
                  <EmptyState
                    compact
                    tone="error"
                    title="사전규격 목록을 불러오지 못했습니다."
                    description="사전규격 API 응답을 확인할 수 없습니다."
                    action={{ label: "다시 시도", onClick: () => { void result.refetch(); } }}
                  />
                ) : items.length === 0 ? (
                  <EmptyState
                    compact
                    title="조건에 맞는 사전규격이 없습니다."
                    description={emptyDescription()}
                    action={searchKey(queryText)
                      ? { label: "검색어만 지우기", onClick: () => applySearch("") }
                      : isDefaultView
                      ? { label: "전체 사전규격 보기", onClick: showAllPreSpecs }
                      : { label: "기본값으로", onClick: restoreDefaults }}
                  />
                ) : (
                  <DenseList aria-label="사전규격" className="pre-specs-list">
                    {items.map((item) => (
                      <PreSpecRow
                        key={item.notice_pk}
                        item={item}
                        isSelected={item.notice_pk === selectedPk}
                        onSelect={() => selectPk(item.notice_pk)}
                        selection={{
                          checked: selection.selectedIdSet.has(item.notice_pk),
                          ariaLabel: `사전규격 선택 · ${titleOf(item)}`,
                          onCheckedChange: () => selection.toggle(item.notice_pk, {
                            id: item.notice_pk,
                            published_at: item.published_at,
                            deadline_at: item.deadline_at,
                            last_observed_at: item.last_observed_at ?? null,
                          }),
                        }}
                        // `Ctrl/Cmd+Enter`는 hook 밖에서 처리한다(발주계획과 같은 모양).
                        onKeyDown={(event) => {
                          if (event.key !== "Enter" || !(event.ctrlKey || event.metaKey)) return;
                          event.preventDefault();
                          openDetail(item.notice_pk);
                        }}
                        {...rowKeyboard.rowProps(item.notice_pk)}
                      />
                    ))}
                  </DenseList>
                )}
              </div>
              <footer className="pre-specs-list-foot">
                <span>{pageCountLabel}</span>
              </footer>
              {/* 페이저는 목록 pane 안쪽 바닥이다(ADR-0062: 발주계획 방식). 클래스와
                  접근 가능한 이름, 단추 이름은 그대로 둔다. */}
              {result.isSuccess && total > PAGE_SIZE ? (
                <ListPager className="pre-specs-pager" label="사전규격 목록 페이지">
                  <button
                    className="interaction-control interaction-control-primary"
                    type="button"
                    disabled={offset === 0}
                    onClick={() => {
                      updateSearchParams({
                        offset: offset - PAGE_SIZE > 0 ? String(offset - PAGE_SIZE) : null,
                      });
                    }}
                  >
                    이전
                  </button>
                  <span>{offset + 1}–{rangeEnd} / {total}</span>
                  <button
                    className="interaction-control interaction-control-primary"
                    type="button"
                    disabled={offset + PAGE_SIZE >= total}
                    onClick={() => {
                      updateSearchParams({ offset: String(offset + PAGE_SIZE) });
                    }}
                  >
                    다음
                  </button>
                </ListPager>
              ) : null}
            </section>

            <section className="review-split-detail pre-specs-detail-pane" aria-label="선택한 사전규격">
              {selectedItem ? (
                <PreSpecDetail
                  key={`${selectedItem.notice_pk}-${trackingFormVersion}`}
                  onReviewExclusion={selectedItem.review_exclusion_status !== "excluded" || workspace === "all"
                    ? () => openExclusion([selectedItem.notice_pk], selectedItem.review_exclusion_status === "excluded" ? "included" : "excluded")
                    : undefined}
                  item={selectedItem}
                  listSearch={listSearch}
                  onOpenDetail={() => openDetail(selectedItem.notice_pk)}
                  onOpenDetailAfterSaved={() => openDetailFromSelection(selectedItem.notice_pk)}
                  onDirtyChange={setTrackingDirty}
                  onSaved={(saved) => {
                    const noticePk = selectedItem.notice_pk;
                    queryClient.setQueryData<PreSpecListResponse>(
                      ["pre-spec-detail", noticePk],
                      (current) => updateTrackingProjection(current, noticePk, saved),
                    );
                    queryClient.setQueriesData<PreSpecListResponse>(
                      { queryKey: ["pre-specs"] },
                      (current) => updateTrackingProjection(current, noticePk, saved),
                    );
                    void queryClient.invalidateQueries({ queryKey: ["pre-spec-overview-pages", noticePk] });
                    void queryClient.invalidateQueries({ queryKey: ["pre-spec-detail", noticePk] });
                    void queryClient.invalidateQueries({ queryKey: ["pre-specs"] });
                    void queryClient.invalidateQueries({ queryKey: ["opportunity", saved.id] });
                  }}
                />
              ) : (
                <div className="pre-specs-detail-empty">
                  <EmptyState
                    compact
                    title="사전규격을 선택하십시오."
                    description="왼쪽 목록에서 행을 선택하면 개요 검토 결과와 추적 선택을 확인할 수 있습니다. 이 선택은 최종 Go/No-Go와 별개입니다."
                  />
                </div>
              )}
            </section>
        </SplitWorkspace>
      </WorkspaceFrame>

      {exclusionTarget ? <ReviewExclusionDialog ids={exclusionTarget.ids} status={exclusionTarget.status}
        onClose={() => setExclusionTarget(null)} onSaved={exclusionSaved} /> : null}
      <Dialog isOpen={scopeDialogOpen} onOpenChange={(open) => { if (!open) setScopeDialogOpen(false); }} purpose="info" width={620}>
        <DialogHeader title="표시 범위" onOpenChange={() => setScopeDialogOpen(false)} />
        <div className="pre-specs-dialog-body">
          <p>
            현재 조건의 서버 전체 건수는 <strong>{total}건</strong>이고, 한 번에 최대 {PAGE_SIZE}건을 불러옵니다.
            {loadedItems.length > 0 ? ` 지금 화면에는 ${loadedItems.length}건이 보입니다.` : ""}
          </p>
          <ul>
            <li>상단 업무 화면 건수는 현재 조건에서 workspace만 바꿔 서버가 센 값(<code className="mono">workspace_counts</code>)이며 페이지 범위와 무관합니다.</li>
            <li>개요 상태·등급·추적 결정·추적 상태·관측일·마감 상태·자동 준비 상태는 모두 서버가 페이지 전에 적용합니다.</li>
            <li>최근 수집의 날짜 범위와 수집 회차는 관측 기록에만 적용하고, 응답 행은 해당 회차의 과거 값이 아닌 현재 projection입니다.</li>
            <li>SW 중심 기본 보기는 SW사업대상=Y와 추적 중인 발주계획에 연결된 예외를 함께 남깁니다. 목록의 <strong>추적 예외</strong>는 SW사업대상이 Y가 아니지만 추적 중인 발주계획에 연결된 건이고, 값이 없는 SW사업대상은 <strong>SW 미확인</strong>으로 적습니다.</li>
            <li>추적 상태는 사업기회 연결이 없으면 <strong>사업기회 미연결</strong>, 연결은 있는데 서버 값이 없으면 <strong>미확인</strong>입니다. 사람이 고른 <strong>미선택</strong>과 다릅니다.</li>
            <li>품질 표식 · 참조 실행과 mock 참조는 운영 완료가 아니고, 표식 없음을 미측정으로 바꾸지 않습니다. 선택한 건의 현재 표식은 개요 검토 결과 머리줄에 있습니다.</li>
          </ul>
        </div>
      </Dialog>
    </section>
  );
}
