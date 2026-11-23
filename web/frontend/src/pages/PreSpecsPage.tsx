import { ReviewPreviewHeader } from "../components/common/ReviewPrimitives";
import { PRE_SPEC_PAGE_SIZE as PAGE_SIZE, preSpecPageOptions } from "../lib/defaultViewCounts";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate, useSearchParams } from "react-router-dom";
import { Button } from "@astryxdesign/core/Button";
import { DateInput } from "@astryxdesign/core/DateInput";
import type { ISODateString } from "@astryxdesign/core/Calendar";
import { Selector } from "@astryxdesign/core/Selector";
import { EmptyState } from "../components/common/EmptyState";
import { PageHeaderTabs } from "../components/common/PageHeaderActions";
import { useUnsavedGuard } from "../components/common/useUnsavedGuard";
import { useRowKeyboardNavigation } from "../components/common/useRowKeyboardNavigation";
import { ListPagerControls, ReviewFilterSegmentedControl, SelectionToolbar, SplitWorkspace } from "../components/common/ReviewPrimitives";
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
import { updateTrackingProjection } from "../components/pre-specs/TrackingDecisionControl";
import { api } from "../lib/api";
import {
  AUTO_PREPARATION_FILTER_VALUES, DEADLINE_SCOPE_OPTIONS, DEADLINE_STATUS_OPTIONS,
  SORT_OPTIONS, TRACKING_STATUS_OPTIONS, VIEWS, WORKSPACES,
  originLabel, titleOf, validAutoPreparationStatus, validDeadlineScope, validDeadlineStatus,
  validObservedDate, validOverviewView, validTrackingDecision, validTrackingStatus,
  validWorkspace, workspaceOf, type WorkspaceKey,
} from "../lib/preSpecViews";
import { PRE_SPEC_AUTO_PREPARATION_STATUS_LABEL } from "../lib/preSpecAutoPreparation";
import { PreSpecBulkDialog, type PreSpecBulkAction } from "../components/pre-specs/PreSpecBulkDialog";
import { PreSpecDetail } from "../components/pre-specs/PreSpecListDetailPane";
import { preSpecColumns } from "../components/pre-specs/PreSpecListRow";
import { RecordTable } from "../components/common/RecordTable";
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
import { buildSourceRunOptions } from "../lib/runOptions";
import { searchKey } from "../lib/search";
import type {
  PreSpecReviewExclusionStatus,
  PreSpecListResponse,
  PreSpecOrigin,
  PreSpecSort,
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
const BUSINESS_DIVISIONS = ["일반용역", "기술용역"] as const;
const ORIGINS: PreSpecOrigin[] = ["추적", "신규"];
// 이전 대시보드의 누적 업무 링크는 workspace를 갖지 않는다. 그 링크의
// 의미(필터 결과 전체)를 보존할 때만 legacy scope를 전체 이력으로 연다.
const LEGACY_DASHBOARD_FILTER_KEYS = [
  "auto_preparation_status",
  "tracking_decision",
  "tracking_status",
] as const;
/** 등급 필터는 2026-11-19에 화면에서 내려갔다(C-1 공고 판정 미가동). 옛 주소에 남은
 * 값은 보이지 않는 필터가 되지 않도록 첫 렌더에서 주소에서 지운다. 표 전환으로 없어진 밀도 값도 지운다. */
const RETIRED_LIST_KEYS = ["grade", "display_grade", "density"] as const;
/** 마감 구간 전환을 쓰는 보기(ADR-0064 결정 2, 2026-11-19 확인 필요에도 적용). */
function scopedWorkspace(value: WorkspaceKey): boolean {
  return value === "actionable" || value === "needs_check";
}

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

export function PreSpecsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const swOnly = searchParams.get("sw_only") !== "false";
  const businessDivision = validDivision(searchParams.get("business_division"));
  const origin = validOrigin(searchParams.get("origin"));
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
  // 마감 구간은 검토할 항목·확인 필요 전용 시야다(ADR-0064 결정 2·6). 다른 보기에
  // 있을 때도 `current`를 싣는다 — 두 탭의 건수가 현재 구간 기준이어야 탭을 눌렀을
  // 때 같은 건수의 목록이 나온다.
  const deadlineScope = scopedWorkspace(workspace) ? validDeadlineScope(searchParams.get("deadline_scope")) : "current";
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
  const deadlineStatus = scopedWorkspace(workspace)
    ? ""
    : validDeadlineStatus(searchParams.get("deadline_status"));
  const queryText = searchParams.get("q") ?? "";
  const requestedSort = validSort(searchParams.get("sort"));
  const sort = requestedSort || sortForWorkspace(workspace);
  const offset = readOffset(searchParams.get("offset"));
  const listParams = new URLSearchParams(searchParams);
  for (const key of RETIRED_LIST_KEYS) listParams.delete(key);
  const listSearch = listParams.toString();
  const selectionFingerprint = preSpecsFilterFingerprint({
    reviewExclusion,
    swOnly,
    businessDivision,
    origin,
    grade: "",
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

  const [bulkTarget, setBulkTarget] = useState<{ ids: number[]; status: PreSpecBulkAction; generation: number } | null>(null);
  const exclusionLanding = useRef<{ active: number | null; index: number; order: number[]; offset: number } | null>(null);
  const [searchText, setSearchText] = useState(queryText);
  const [advancedOpen, setAdvancedOpen] = useState(false);
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
    title: "추적 결정 입력을 저장하지 않고 옮겨요",
    message: "저장하지 않은 추적 결정 사유와 담당자 이름이 있어요. 지금 옮기면 사라지며 저장된 추적 상태는 바뀌지 않아요.",
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
    const hasRetiredParams = RETIRED_LIST_KEYS.some((key) => searchParams.has(key));
    if (!hasRetiredParams && !hasLegacyView && !hasLegacyDashboardFilter) return;
    const next = new URLSearchParams(searchParams);
    for (const key of RETIRED_LIST_KEYS) next.delete(key);
    if (hasLegacyView) {
      next.delete("view");
      next.set("overview_view", overviewView);
    }
    if (hasLegacyView || hasLegacyDashboardFilter) next.set("workspace", "all");
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
  // 옵션 문구는 공용 조립기가 만든다(`lib/runOptions.ts`). 목록에 없는 URL 값은 조용히
  // 다른 회차로 바뀌지 않고 사유만 붙는다.
  const selectedRunLabel = useMemo(() => {
    if (!sourceRunId) return null;
    const options = buildSourceRunOptions({
      runs: sourceRuns,
      selectedRunId: sourceRunId,
      isError: runsQuery.isError,
    });
    return options.find((option) => option.value === sourceRunId)?.label ?? "선택한 회차 (목록에 없음)";
  }, [runsQuery.isError, sourceRunId, sourceRuns]);

  const listQuery = useMemo(
    () => ({
      review_exclusion: reviewExclusion as "all" | PreSpecReviewExclusionStatus,
      // 구간은 actionable·needs_check 술어의 일부라 다른 보기의 행·건수를 바꾸지 않는다.
      // 그래서 항상 싣고, 서버는 그 두 칸에만 반영한다.
      deadline_scope: deadlineScope,
      sw_only: swOnly,
      business_division: businessDivision || null,
      origin: origin || null,
      auto_preparation_status: autoPreparationStatus || null,
      workspace,
      overview_view: overviewView,
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
    [reviewExclusion, autoPreparationStatus, businessDivision, deadlineScope, deadlineStatus, offset, origin, overviewView, queryText, rawObservedFrom, rawObservedTo, sort, sourceRunId, swOnly, trackingDecision, trackingStatus, workspace],
  );
  const result = useQuery({
    ...preSpecPageOptions(listQuery, searchKey(queryText)),
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
  // 구간 적용 **전** 활성 보기(검토할 항목 또는 확인 필요)를 둘로 나눈 서버 건수다.
  // 받은 건수만 표시하고 아직 응답이 없으면 구간 이름만 표시한다.
  const deadlineScopeCounts = workspace === "needs_check"
    ? result.data?.needs_check_deadline_scope_counts
    : result.data?.deadline_scope_counts;
  const deadlineScopeCount = (key: "current" | "passed"): number | null => {
    if (!result.isSuccess) return null;
    return deadlineScopeCounts?.[key] ?? null;
  };
  const isDefaultView = workspace === "actionable" && swOnly && !businessDivision && !origin && !queryText
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
      setSelectionMessage("선택한 항목의 게시·마감·관측 시각을 확인할 수 없어 선택 검토를 시작하지 못했어요.");
      return;
    }
    const durable = selection.persist();
    if (!durable.ok) {
      setSelectionMessage(durable.error?.message ?? "선택 검토 순서를 저장하지 못했어요.");
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
      setSelectionMessage("선택한 항목의 게시·마감·관측 시각을 확인할 수 없어 선택 검토를 시작하지 못했어요.");
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

  function openBulk(ids: readonly number[], status: PreSpecBulkAction) {
    if (ids.length === 0 || ids.length > 200) return;
    trackingGuard.confirmDiscard(() => {
      setBulkTarget({ ids: [...ids], status, generation: selection.state.selectionGeneration });
    });
  }

  async function bulkSaved(ids: number[], message?: string) {
    setSelectionMessage(message ?? null);
    exclusionLanding.current = { offset, active: selectedPk, index: items.findIndex((item) => item.notice_pk === selectedPk), order: itemKeys };
    selection.applyResult(ids, bulkTarget?.generation);
    setTrackingDirty(false);
    // Remove the discarded tracking draft even when the active row remains visible.
    setTrackingFormVersion((version) => version + 1);
    setBulkTarget(null);
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["pre-specs"] }),
      ...(bulkTarget?.status === "track" ? [
        queryClient.invalidateQueries({ queryKey: ["opportunity"] }),
        queryClient.invalidateQueries({ queryKey: ["opportunities"] }),
      ] : []),
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
      review_exclusion: null,
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
    if (searchKey(queryText)) return `적용된 검색어 "${queryText}"와 다른 활성 필터에 맞는 사전규격이 없어요.`;
    // 구간은 검토할 항목의 시야이지 항목을 없애는 필터가 아니다(ADR-0064 결정 1).
    // 비었으면 다른 구간에 무엇이 남아 있는지 서버 건수로 알린다.
    if (scopedWorkspace(workspace) && deadlineScope === "passed") {
      return workspace === "needs_check"
        ? "마감 경과 구간에 확인 필요 건이 없어요. 마감 전·미확인 구간으로 돌아가 주세요."
        : "마감 경과 구간에 검토할 항목이 없어요. 마감 전·미확인 구간으로 돌아가 주세요.";
    }
    if (scopedWorkspace(workspace) && deadlineScope === "current" && (deadlineScopeCounts?.passed ?? 0) > 0) {
      return `마감 전·미확인 구간에는 없어요. 마감 경과 ${deadlineScopeCounts?.passed}건은 구간 전환으로 볼 수 있어요.`;
    }
    if (workspace === "needs_check") return "개요가 실패·취소로 끝났거나 문서 준비가 멈춘 건이 없어요.";
    if (isDefaultView) return "SW 중심 기본 보기에 맞는 항목이 없어요. 전체 보기는 SW사업대상과 무관한 사전규격까지 명시적으로 요청해요.";
    if (overviewView !== "all") return `현재 개요 상태 보기와 필터에 맞는 사전규격이 없어요. 보기를 바꾸거나 조건을 넓혀 보세요.`;
    if (swOnly) return "SW 중심 기본 보기와 추가 필터가 함께 적용되어 있어요. 기본값으로 돌아가거나 조건을 조정해 보세요.";
    if (autoPreparationStatus || trackingDecision || trackingStatus || sourceRunId || observedFrom || observedTo || deadlineStatus) {
      return "현재 선택한 업무구분·구분·추적·관측·마감 조건에 맞는 누적 데이터가 없어요.";
    }
    if (businessDivision || origin || queryText) return "현재 선택한 업무구분·구분·검색어 조건에 맞는 누적 데이터가 없어요.";
    return "누적 수집된 사전규격 데이터가 아직 없어요.";
  }

  const activeWorkspace = workspaceOf(workspace);
  /**
   * 접힌 상세 필터에 걸려 있는 조건 수(명세 §2.1, U3). 상세 필터 안의 축 가운데
   * 기본값이 아닌 것을 센다 — `필터 초기화`(`기본값으로`)가 되돌리는 것과 같은
   * 집합이다. 보기 탭·검색·SW 스위치·마감 구간은 늘 보이는 컨트롤이라 세지 않는다.
   * 표시 순서(`sort`)도 세지 않는다 — 정렬은 결과 집합을 바꾸지 않는 필터가 아니다.
   */
  const activeFilterCount = [
    !swOnly,
    reviewExclusion !== "all",
    deadlineScope !== "current",
    Boolean(rawObservedFrom || rawObservedTo),
    sort !== sortForWorkspace(workspace),
    overviewView !== "all",
    Boolean(businessDivision),
    Boolean(origin),
    Boolean(trackingStatus),
    Boolean(deadlineStatus),
    Boolean(autoPreparationStatus),
    Boolean(trackingDecision),
    Boolean(sourceRunId),
  ].filter(Boolean).length;

  const appliedFilters: AppliedFilter[] = [];
  function addFilter(key: string, label: string) {
    appliedFilters.push({ key, label, onRemove: () => updateSearchParams({ [key]: null }) });
  }

  if (!swOnly) addFilter("sw_only", "SW 중심 해제");
  if (reviewExclusion !== "all") addFilter("review_exclusion", reviewExclusion === "excluded" ? "검토 제외만" : "검토 포함만");
  if (deadlineScope === "passed") addFilter("deadline_scope", "마감 구간 · 마감 경과");
  if (rawObservedFrom || rawObservedTo) {
    appliedFilters.push({
      key: "observed_range",
      label: `관측 · ${observedFrom || "시작 제한 없음"}–${observedTo || "종료 제한 없음"}`,
      onRemove: () => updateSearchParams({ observed_from: null, observed_to: null }),
    });
  }
  if (overviewView !== "all") addFilter("overview_view", `개요 상태 · ${VIEWS.find((view) => view.key === overviewView)?.label ?? overviewView}`);
  if (businessDivision) addFilter("business_division", `업무구분 · ${businessDivision}`);
  if (origin) addFilter("origin", `발견 구분 · ${originLabel(origin)}`);
  if (trackingStatus) addFilter("tracking_status", `추적 상태 · ${trackingStatus}`);
  if (deadlineStatus) addFilter("deadline_status", `마감 상태 · ${DEADLINE_STATUS_OPTIONS.find((option) => option.value === deadlineStatus)?.label ?? deadlineStatus}`);
  if (autoPreparationStatus) addFilter("auto_preparation_status", `자동 준비 · ${PRE_SPEC_AUTO_PREPARATION_STATUS_LABEL[autoPreparationStatus]}`);
  if (trackingDecision) addFilter("tracking_decision", "추적 결정 · 대기");
  if (sourceRunId && selectedRunLabel) addFilter("source_run_id", `수집 회차 · ${selectedRunLabel}`);

  return (
    <section className="pre-specs-page" data-astryx-theme="bidops" aria-labelledby="page-title">
      {/* 화면 제목은 셸 상단바가 그린다(제목 모드). 페이지는 같은 이름을 세로로 한 번
          더 쓰지 않고, `aria-labelledby`가 가리킬 숨긴 제목만 남긴다. 페이지 상태를
          쓰는 액션(`표시 범위`)은 상단바 슬롯으로 portal한다. */}
      <span className="visually-hidden" id="page-title">사전규격</span>

      <PageHeaderTabs>
        <WorkspaceFilterBar activeFilterCount={activeFilterCount} aria-label="사전규격 필터" className="pre-specs-filters">
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
          </WorkspaceFilterLine>

          <WorkspaceFilterTools className="pre-specs-filter-tools">
            <AppliedFilterTokens filters={appliedFilters} />
            <WorkspaceAdvancedToggle
              visibleLabel="필터"
              activeCount={activeFilterCount}
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
          </WorkspaceFilterTools>

          <WorkspaceFilterAdvanced
            isOpen={advancedOpen}
            onClose={() => setAdvancedOpen(false)}
            id="pre-specs-advanced-filters"
            onReset={restoreDefaults}
            resetLabel="기본값으로"
          >
            <WorkspaceFilterGroup title="조회 범위">
              <label
                className="pre-specs-switch"
                title={swOnly ? "일반·기술용역 / SW사업대상 Y + 추적 예외" : "SW사업대상과 무관한 사전규격까지 조회"}
              >
                <input
                  aria-label="SW 중심 · 추적 예외 포함"
                  checked={swOnly}
                  type="checkbox"
                  onChange={(event) => updateSearchParams({ sw_only: event.target.checked ? null : "false" })}
                />
                <span>SW 중심</span>
              </label>
              <div className="pre-specs-filter-context-range">
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
              {workspace === "all" ? <Selector label="검토 포함 여부" size="sm"
                options={[{ value: "all", label: "전체" }, { value: "included", label: "검토 포함" }, { value: "excluded", label: "검토 제외" }]}
                value={reviewExclusion} onChange={(value) => updateSearchParams({ review_exclusion: value === "all" ? null : value })} /> : null}
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
              {/* 회차는 다른 축과 같은 방식으로 **기존 조건에 더한다**(시안 M1 승인 결정 2). */}
              <SourceRunFilter
                allRunsDescription="관측 이력 전체"
                isError={runsQuery.isError}
                isPending={runsQuery.isPending}
                onChange={(runId) => updateSearchParams({ source_run_id: runId })}
                onRetry={() => { void runsQuery.refetch(); }}
                runs={sourceRuns}
                value={sourceRunId || null}
              />
            </WorkspaceFilterGroup>
            <WorkspaceFilterGroup title="개요 검토">
              <Selector
                label="개요 상태"
                size="sm"
                options={VIEWS.map((definition) => ({ value: definition.key, label: definition.label }))}
                value={overviewView}
                onChange={(value) => updateSearchParams({ overview_view: value === "all" ? null : value })}
              />
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
            </WorkspaceFilterGroup>
            <WorkspaceFilterGroup title="추적·일정">
              {scopedWorkspace(workspace) ? (
                <div className="pre-specs-deadline-scope">
                  <span className="pre-specs-deadline-scope-caption">마감 구간</span>
                  <ReviewFilterSegmentedControl
                    className="pre-specs-deadline-scope-control"
                    label="마감 구간"
                    layout="hug"
                    onChange={(value) => updateSearchParams({ deadline_scope: value === "current" ? null : value })}
                    options={DEADLINE_SCOPE_OPTIONS.map((option) => {
                      const count = deadlineScopeCount(option.value);
                      return {
                        value: option.value,
                        label: count === null ? option.label : `${option.label} ${formatCount(count)}`,
                      };
                    })}
                    value={deadlineScope}
                  />
                </div>
              ) : null}
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
              {!scopedWorkspace(workspace) ? (
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
            </WorkspaceFilterGroup>
          </WorkspaceFilterAdvanced>

          {/* 회차 줄 — 상세 필터를 접었는지와 무관하게 그린다(명세 §2.1). */}
          {sourceRunId && selectedRunLabel ? (
            <WorkspaceFilterContext className="pre-specs-filter-context">
              <SourceRunContextLine
                label={selectedRunLabel}
                onClearRun={() => updateSearchParams({ source_run_id: null })}
                reason={runsQuery.isError ? "회차 목록 조회 실패" : null}
              />
            </WorkspaceFilterContext>
          ) : null}
        </WorkspaceFilterBar>
      </PageHeaderTabs>
      <WorkspaceFrame>

        {/* 조회 중이거나 실패해도 좌우 분할 골격은 그대로 두고 상태를 목록 pane 안에
            그린다(ADR-0062: 발주계획 방식). 화면이 통째로 접혔다 펴지면 사람이 보던
            자리를 잃는다. */}
        <SplitWorkspace className="pre-specs-split-workspace">
            <section className="review-split-list pre-specs-list-pane" aria-label="사전규격 목록">
              <header className="review-list-head pre-specs-list-head">
                <p className="pre-specs-list-heading" title={activeWorkspace.description}>
                  <span className="pre-specs-list-count">
                    {activeWorkspace.label} {result.isError
                      ? "건수 확인 불가"
                      : result.isPending
                        ? "불러오는 중"
                        : <><span className="mono tabular-nums">{formatCount(total)}</span>건</>}
                  </span>
                  <span className="pre-specs-list-scope"> · {SORT_OPTIONS.find((option) => option.value === sort)?.label}</span>
                </p>
              </header>
              <SelectionToolbar
                className="pre-specs-selection-toolbar"
                count={selection.selectedIds.length}
                countClassName="pre-specs-selection-count"
                label="사전규격 선택 작업"
                reasonClassName="pre-specs-selection-disabled-reason"
                reasonId="pre-specs-selection-disabled"
                reason={!selection.hydrationReady
                  ? "선택 저장소를 준비하는 중이에요."
                  : !selection.storageAvailable
                    ? "이 탭의 선택 저장소를 사용할 수 없어 검토 순서를 저장할 수 없어요."
                  : selection.selectedIds.length > 0 && !selectedReviewIds
                      ? "선택 항목의 정렬 시각을 확인할 수 없어요."
                      : ""}
                selectPage={{
                  onClick: selectCurrentPage,
                  disabled: !selection.hydrationReady || !selection.storageAvailable || items.length === 0 || pageFullySelected,
                }}
                clearSelection={{ onClick: selection.clear, disabled: selection.selectedIds.length === 0 }}
                startTracking={{
                  onClick: () => openBulk(selection.selectedIds, "track"),
                  disabled: !selection.hydrationReady || !selection.storageAvailable || selection.selectedIds.length === 0 || selection.selectedIds.length > 200,
                }}
                actions={(
                  <>
                    <Button size="sm" variant="secondary" aria-label="검토 목록에서 제외" label="검토 제외"
                      isDisabled={!selection.hydrationReady || !selection.storageAvailable || selection.selectedIds.length === 0 || selection.selectedIds.length > 200}
                      onClick={() => openBulk(selection.selectedIds, "excluded")} />
                    <button
                      className="interaction-control"
                      type="button"
                      onClick={reviewSelected}
                      disabled={!selection.hydrationReady || !selection.storageAvailable || selection.selectedIds.length === 0 || !selectedReviewIds}
                      aria-label="선택 항목 검토"
                      aria-describedby="pre-specs-selection-disabled"
                    >
                      선택 검토
                    </button>
                  </>
                )}
              />
              {selection.selectedIds.length > 200 ? <p role="alert">한 번에 200건까지 일괄 처리할 수 있어요. 선택을 줄여 주세요.</p> : null}
              {selectionMessage ? <p className="pre-specs-selection-message" role="alert">{selectionMessage}</p> : null}

              <RecordTable
                activeKey={selectedPk}
                className="pre-specs-list-scroll"
                columns={preSpecColumns(workspace === "actionable" || workspace === "needs_check")}
                getKey={(item) => item.notice_pk}
                getRowLabel={titleOf}
                label="사전규격"
                navigation={rowKeyboard}
                onActivate={selectPk}
                onRowKeyDown={(event, item) => {
                  if (event.key !== "Enter" || !(event.ctrlKey || event.metaKey)) return;
                  event.preventDefault();
                  openDetail(item.notice_pk);
                }}
                onScroll={(event) => selection.setListScrollTop(event.currentTarget.scrollTop)}
                rowClassName="pre-specs-row"
                rows={items}
                selection={{
                  getChecked: (item) => selection.selectedIdSet.has(item.notice_pk),
                  getLabel: (item) => `사전규격 선택 · ${titleOf(item)}`,
                  onCheckedChange: (item) => selection.toggle(item.notice_pk, {
                    id: item.notice_pk,
                    published_at: item.published_at,
                    deadline_at: item.deadline_at,
                    last_observed_at: item.last_observed_at ?? null,
                  }),
                }}
                state={result.isPending ? {
                  kind: "loading", label: "사전규격 목록을 불러오는 중이에요.", lines: 3, showLabel: true,
                } : result.isError ? {
                  kind: "error",
                  message: {
                    title: "사전규격 목록을 불러오지 못했어요",
                    description: "사전규격 API 응답을 확인할 수 없어요.",
                    action: { label: "다시 시도", onClick: () => { void result.refetch(); } },
                  },
                } : items.length === 0 ? {
                  kind: "empty",
                  message: {
                    title: "조건에 맞는 사전규격이 없어요",
                    description: emptyDescription(),
                    action: searchKey(queryText)
                      ? { label: "검색어만 지우기", onClick: () => applySearch("") }
                      : isDefaultView
                      ? { label: "전체 사전규격 보기", onClick: showAllPreSpecs }
                      : { label: "기본값으로", onClick: restoreDefaults },
                  },
                } : undefined}
                viewportRef={listRef}
              />
              {/* 페이저는 목록 pane 안쪽 바닥이고 네 화면이 같은 공용 부품을 쓴다
                  (명세 §2.2). 한 쪽에 다 들어오는 목록에서도 줄을 남기고 단추만 끈다 —
                  그래서 전체 건수를 적던 별도 바닥 줄(`pre-specs-list-foot`)은 없앴다. */}
              {result.isSuccess ? (
                <ListPagerControls
                  className="pre-specs-pager"
                  keyboardAction="상세 열기"
                  label="사전규격 목록 페이지"
                  offset={offset}
                  onNext={() => updateSearchParams({ offset: String(offset + PAGE_SIZE) })}
                  onPrevious={() => updateSearchParams({
                    offset: offset - PAGE_SIZE > 0 ? String(offset - PAGE_SIZE) : null,
                  })}
                  total={total}
                  visibleCount={loadedItems.length}
                />
              ) : null}
            </section>

            <section className="review-split-detail pre-specs-detail-pane" aria-label="선택한 사전규격">
              <ReviewPreviewHeader />
              {selectedItem ? (
                <PreSpecDetail
                  key={`${selectedItem.notice_pk}-${trackingFormVersion}`}
                  onReviewExclusion={selectedItem.review_exclusion_status !== "excluded" || workspace === "all"
                    ? () => openBulk([selectedItem.notice_pk], selectedItem.review_exclusion_status === "excluded" ? "included" : "excluded")
                    : undefined}
                  item={selectedItem}
                  listSearch={listSearch}
                  onOpenDetail={() => openDetail(selectedItem.notice_pk)}
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
                    title="사전규격을 선택해 주세요"
                    description="왼쪽 목록에서 행을 선택하면 개요 검토 결과와 추적 선택을 확인할 수 있어요. 이 선택은 최종 Go/No-Go와 별개예요."
                  />
                </div>
              )}
            </section>
        </SplitWorkspace>
      </WorkspaceFrame>

      {bulkTarget ? <PreSpecBulkDialog ids={bulkTarget.ids} status={bulkTarget.status}
        onClose={() => setBulkTarget(null)} onSaved={bulkSaved} /> : null}
    </section>
  );
}
