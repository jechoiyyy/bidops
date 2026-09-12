import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate, useSearchParams } from "react-router-dom";
import { Button } from "@astryxdesign/core/Button";
import { Dialog, DialogHeader } from "@astryxdesign/core/Dialog";
import { Selector } from "@astryxdesign/core/Selector";
import { EmptyState } from "../components/common/EmptyState";
import { PageHeaderActions } from "../components/common/PageHeaderActions";
import { useUnsavedGuard } from "../components/common/useUnsavedGuard";
import { useRowKeyboardNavigation } from "../components/common/useRowKeyboardNavigation";
import { DenseList, SplitWorkspace } from "../components/common/ReviewPrimitives";
import {
  WorkspaceAdvancedToggle,
  WorkspaceFilterAdvanced,
  WorkspaceFilterBar,
  WorkspaceFilterContext,
  WorkspaceFilterEnd,
  WorkspaceFilterLine,
  WorkspaceFrame,
  WorkspaceSearch,
  WorkspaceViewTabs,
} from "../components/common/WorkspaceFilters";
import { updateTrackingProjection } from "../components/pre-specs/TrackingDecisionControl";
import { api } from "../lib/api";
import {
  AUTO_PREPARATION_FILTER_VALUES, GRADE_FILTER_VALUES, SORT_OPTIONS, VIEWS,
  matchesGradeFilter, matchesTrackingDecision, matchesView,
  validAutoPreparationStatus, validGrade, validTrackingDecision, validView, viewOf, type ViewKey,
} from "../lib/preSpecViews";
import { PRE_SPEC_AUTO_PREPARATION_STATUS_LABEL } from "../lib/preSpecAutoPreparation";
import { PreSpecDetail } from "../components/pre-specs/PreSpecListDetailPane";
import { PreSpecRow } from "../components/pre-specs/PreSpecListRow";
import type {
  PreSpecListResponse,
  PreSpecOrigin,
  PreSpecOverviewReviewStatus,
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
// 이 크기면 한 화면에서 보기와 목록이 대체로 일치한다. 그래도 전체 건수가 페이지
// 크기를 넘으면 **보기 버튼의 건수(서버 전체 집계)와 실제로 보이는 행 수가 다르다.**
// 그 사실은 목록 바닥과 부분 표시 문구가 글자로 밝힌다 — 조용히 숨기지 않는다.
const PAGE_SIZE = 200;
const BUSINESS_DIVISIONS = ["일반용역", "기술용역"] as const;
const ORIGINS: PreSpecOrigin[] = ["추적", "신규"];

/** 상세 필터 Selector의 "전체"를 나타내는 표식값. URL에는 실리지 않는다. */
const ALL_OPTION = "__all__";

function validDivision(value: string | null): string {
  return value && BUSINESS_DIVISIONS.includes(value as (typeof BUSINESS_DIVISIONS)[number]) ? value : "";
}

function validOrigin(value: string | null): PreSpecOrigin | "" {
  return value && ORIGINS.includes(value as PreSpecOrigin) ? (value as PreSpecOrigin) : "";
}

function validSort(value: string | null): PreSpecSort {
  return value === "deadline" ? "deadline" : "published";
}

function readOffset(value: string | null): number {
  const parsed = Number(value ?? "0");
  return Number.isInteger(parsed) && parsed >= 0 ? parsed : 0;
}

export function PreSpecsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const swOnly = searchParams.get("sw_only") !== "false";
  const businessDivision = validDivision(searchParams.get("business_division"));
  const origin = validOrigin(searchParams.get("origin"));
  const gradeFilter = validGrade(searchParams.get("grade"));
  // 서버 필터(질의 인자가 있다)와 페이지 한정 필터를 섞지 않는다.
  const autoPreparationStatus = validAutoPreparationStatus(searchParams.get("auto_preparation_status"));
  const trackingDecision = validTrackingDecision(searchParams.get("tracking_decision"));
  const view = validView(searchParams.get("view"));
  const queryText = searchParams.get("q") ?? "";
  const sort = validSort(searchParams.get("sort"));
  const offset = readOffset(searchParams.get("offset"));

  const [searchText, setSearchText] = useState(queryText);
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [scopeDialogOpen, setScopeDialogOpen] = useState(false);
  const [trackingDialogOpen, setTrackingDialogOpen] = useState(false);
  // 저장하지 않은 입력이 있는 채로 창을 닫으려 한 상태. 창은 열린 채로 두고
  // 같은 창 안에서 확인을 받는다.
  const [trackingCloseRequested, setTrackingCloseRequested] = useState(false);
  const [selectedPk, setSelectedPk] = useState<number | null>(null);
  const listRef = useRef<HTMLDivElement | null>(null);
  // 대화상자의 추적 결정 입력(사유·담당자)은 행을 바꾸거나 창을 닫으면 사라진다.
  // route 이동은 컨트롤이 스스로 막으므로 여기서는 행 전환·닫기만 확인한다.
  const [trackingDirty, setTrackingDirty] = useState(false);
  const trackingGuard = useUnsavedGuard(trackingDirty, {
    scope: "pathname",
    title: "추적 결정 입력을 저장하지 않고 옮깁니다",
    message: "저장하지 않은 추적 결정 사유와 담당자 이름이 있습니다. 지금 옮기면 사라지며 저장된 추적 상태는 바뀌지 않습니다.",
    confirmLabel: "저장하지 않고 옮기기",
  });

  useEffect(() => setSearchText(queryText), [queryText]);

  const listQuery = useMemo(
    () => ({
      sw_only: swOnly,
      business_division: businessDivision || null,
      origin: origin || null,
      auto_preparation_status: autoPreparationStatus || null,
      q: queryText || null,
      sort,
      limit: PAGE_SIZE,
      offset,
    }),
    [autoPreparationStatus, businessDivision, offset, origin, queryText, sort, swOnly],
  );
  const result = useQuery({
    queryKey: ["pre-specs", listQuery],
    queryFn: ({ signal }) => api.getPreSpecs(listQuery, { signal }),
    // 기본값으로 돌아왔을 때도 sw_only=true 요청을 다시 보내 ADR-0031의 서버 기본
    // projection과 화면 상태가 같은지 확인한다.
    staleTime: 0,
  });

  const loadedItems = useMemo(() => result.data?.items ?? [], [result.data]);
  // 서버에 등급 질의가 없으므로 여기서 고른다. 판정의 재계산이 아니라 서버가 준
  // `grade` 값으로 행을 고르는 것뿐이다.
  const gradeFiltered = useMemo(
    () => loadedItems.filter((item) => matchesGradeFilter(item, gradeFilter)),
    [gradeFilter, loadedItems],
  );
  // 추적 결정 대기도 서버 질의 인자가 없어 등급 필터와 같은 페이지 한정 필터다.
  const items = useMemo(
    () => gradeFiltered
      .filter((item) => matchesTrackingDecision(item, trackingDecision))
      .filter((item) => matchesView(item, view)),
    [gradeFiltered, trackingDecision, view],
  );
  const total = result.data?.total ?? 0;
  const overviewStatusCounts = useMemo(() => result.data?.overview_status_counts ?? [], [result.data]);
  const listSearch = searchParams.toString();
  const isDefaultView = swOnly && !businessDivision && !origin && !gradeFilter && !queryText
    && !autoPreparationStatus && !trackingDecision
    && view === "all" && sort === "published" && offset === 0;

  /** 보기 버튼의 건수는 **서버 전체 집계**다. 등급 필터와 페이지 범위는 반영하지
   * 않으므로 실제로 보이는 행 수와 다를 수 있고, 그 사실을 화면이 밝힌다. */
  const viewCounts = useMemo(() => {
    const byStatus = new Map<PreSpecOverviewReviewStatus | null, number>();
    for (const row of overviewStatusCounts) byStatus.set(row.status, row.count);
    const counts = new Map<ViewKey, number>();
    for (const definition of VIEWS) {
      counts.set(
        definition.key,
        definition.statuses === null
          ? total
          : definition.statuses.reduce((sum, status) => sum + (byStatus.get(status) ?? 0), 0),
      );
    }
    return counts;
  }, [overviewStatusCounts, total]);
  const serverViewCount = viewCounts.get(view) ?? 0;

  const itemKeys = useMemo(() => items.map((item) => item.notice_pk), [items]);
  const selectedItem = items.find((item) => item.notice_pk === selectedPk) ?? null;

  // 목록이 바뀌어 선택이 사라지면 첫 행을 고른다. 사람이 고르는 중이던 입력은
  // 대화상자 안에 있고, 그 확인은 아래 `selectPk`가 맡는다.
  useEffect(() => {
    if (items.length === 0) {
      if (selectedPk !== null) setSelectedPk(null);
      return;
    }
    if (!items.some((item) => item.notice_pk === selectedPk)) {
      setSelectedPk(items[0].notice_pk);
      setTrackingDialogOpen(false);
      setTrackingCloseRequested(false);
    }
  }, [items, selectedPk]);

  const selectPk = useCallback((next: number) => {
    trackingGuard.confirmDiscard(() => {
      setSelectedPk(next);
      setTrackingDialogOpen(false);
      setTrackingCloseRequested(false);
    });
  }, [trackingGuard]);

  // 상세 화면으로 가는 것도 저장하지 않은 입력을 버릴 수 있으므로 같은 확인을 거친다.
  const openDetail = useCallback((noticePk: number) => {
    trackingGuard.confirmDiscard(() => {
      navigate(`/pre-specs/${noticePk}${listSearch ? `?${listSearch}` : ""}`);
    });
  }, [listSearch, navigate, trackingGuard]);

  const rowKeyboard = useRowKeyboardNavigation<number>({
    containerRef: listRef,
    keys: itemKeys,
    selectedKey: selectedPk,
    onSelect: selectPk,
    // 경계에서는 페이지를 넘긴다. 서버 전체가 한 페이지보다 클 때만 움직인다.
    onBoundary: (direction) => {
      if (direction === "next" && offset + PAGE_SIZE < total) {
        updateSearchParams({ offset: String(offset + PAGE_SIZE) });
      } else if (direction === "previous" && offset > 0) {
        updateSearchParams({ offset: offset - PAGE_SIZE > 0 ? String(offset - PAGE_SIZE) : null });
      }
    },
  });

  const changeTrackingDialog = useCallback((open: boolean) => {
    if (open) {
      setTrackingDialogOpen(true);
      setTrackingCloseRequested(false);
      return;
    }
    // 저장하지 않은 입력이 있으면 창을 닫지 않고 확인을 먼저 보여 준다.
    if (trackingDirty) {
      setTrackingCloseRequested(true);
      return;
    }
    setTrackingDialogOpen(false);
    setTrackingCloseRequested(false);
  }, [trackingDirty]);

  function updateSearchParams(changes: Record<string, string | null>) {
    const next = new URLSearchParams(searchParams);
    for (const [key, value] of Object.entries(changes)) {
      if (value === null || value === "") next.delete(key);
      else next.set(key, value);
    }
    // 필터가 바뀌면 페이지를 처음으로 돌린다. 좁힌 조건에서 3페이지째를 보여 주는
    // 것은 사람이 요청한 적 없는 상태다. 단, 호출자가 `offset`을 명시적으로 준
    // 경우(키보드 경계 이동)는 그것이 요청된 페이지이므로 지우지 않는다.
    if (!Object.prototype.hasOwnProperty.call(changes, "offset")) next.delete("offset");
    setSearchParams(next, { replace: true });
  }

  function restoreDefaults() {
    updateSearchParams({
      sw_only: null,
      business_division: null,
      origin: null,
      grade: null,
      auto_preparation_status: null,
      tracking_decision: null,
      q: null,
      sort: null,
      view: null,
    });
    setSearchText("");
  }

  function showAllPreSpecs() {
    updateSearchParams({ sw_only: "false" });
  }

  function emptyDescription(): string {
    if (isDefaultView) return "SW 중심 기본 보기에 맞는 항목이 없습니다. 전체 보기는 SW사업대상과 무관한 사전규격까지 명시적으로 요청합니다.";
    if (view !== "all") return `현재 보기(${viewOf(view).label})와 필터에 맞는 행이 불러온 목록에 없습니다. 보기를 바꾸거나 조건을 넓혀 보십시오.`;
    if (swOnly) return "SW 중심 기본 보기와 추가 필터가 함께 적용되어 있습니다. 기본값으로 돌아가거나 조건을 조정해 보십시오.";
    // 불러온 행을 페이지 한정 필터가 걸러 낸 경우를 `데이터 없음`으로 적지 않는다.
    if (trackingDecision && loadedItems.length > 0) {
      return "불러온 페이지에는 추적 결정 대기 상태인 행이 없습니다. 추적 결정 필터를 끄거나 다음 페이지를 확인하십시오.";
    }
    if (autoPreparationStatus) return "선택한 자동 준비 상태에 해당하는 사전규격이 없습니다.";
    if (businessDivision || origin || gradeFilter || queryText || trackingDecision) return "현재 선택한 업무구분·구분·등급·추적 결정·검색어 조건에 맞는 누적 데이터가 없습니다.";
    return "누적 수집된 사전규격 데이터가 아직 없습니다.";
  }

  const rangeEnd = Math.min(offset + loadedItems.length, total);
  // 보이는 행 수와 서버 집계가 다른 경우. 페이지 범위나 등급 필터 때문이며,
  // 어느 쪽이든 그 이유를 함께 적는다.
  const isPartial = serverViewCount !== items.length;

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
            {/* 건수는 서버 전체 집계다. 아직 못 불러왔으면 0으로 채우지 않고 `–`로
                남긴다(`null`) — 미로딩과 0건은 서로 다른 사실이다. `취소`는 실패와
                뜻이 달라 자기 보기를 갖되, 건수가 0이고 지금 보고 있지도 않으면
                자리만 차지하므로 감춘다. */}
            <WorkspaceViewTabs
              className="pre-specs-views"
              label="개요 검토 상태 보기"
              onChange={(key) => updateSearchParams({ view: key === "all" ? null : key })}
              tabs={VIEWS.filter((definition) => (
                definition.key !== "cancelled" || view === "cancelled" || (viewCounts.get("cancelled") ?? 0) > 0
              )).map((definition) => ({
                key: definition.key,
                label: definition.label,
                count: result.isSuccess ? viewCounts.get(definition.key) ?? 0 : null,
              }))}
              value={view}
            />
            <WorkspaceFilterEnd>
              {/* `q`는 서버 질의 인자다. 글자를 칠 때마다 목록을 다시 부르지 않고
                  Enter로 적용한다(적용 시점은 데이터 원천이 정한다). */}
              <WorkspaceSearch
                label="사업명·기관명 검색"
                onChange={setSearchText}
                onEnter={() => updateSearchParams({ q: searchText.trim() || null })}
                value={searchText}
              />
              <WorkspaceAdvancedToggle
                controlsId="pre-specs-advanced-filters"
                isOpen={advancedOpen}
                onToggle={() => setAdvancedOpen((open) => !open)}
              />
            </WorkspaceFilterEnd>
          </WorkspaceFilterLine>

          <WorkspaceFilterContext className="pre-specs-filter-context">
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
            {/* 기본 화면에는 설명 문단을 두지 않는다. 필터의 적용 범위는 목록
                바닥의 짧은 문구와 `표시 범위` 대화상자가 갖는다. 등급 필터는 서버가
                거르지 못하는 필터라 켜져 있을 때만 한 줄로 밝힌다. */}
            {gradeFilter || trackingDecision ? (
              <p className="pre-specs-grade-filter-note" role="status">
                {gradeFilter && trackingDecision
                  ? "등급·추적 결정 필터는"
                  : gradeFilter ? "등급 필터는" : "추적 결정 필터는"}
                {" 불러온 페이지에만 적용됩니다. 보기 건수는 서버 전체 집계입니다."}
              </p>
            ) : null}
          </WorkspaceFilterContext>

          {advancedOpen ? (
            <WorkspaceFilterAdvanced
              columns={4}
              id="pre-specs-advanced-filters"
              onReset={restoreDefaults}
              resetLabel="기본값으로"
            >
              {/* `전체`는 값이 없는 상태이지 다섯 번째 선택지가 아니다. Selector에는
                  빈 문자열을 줄 수 없어 표식값(ALL_OPTION)으로 두고, URL에는 인자를
                  지우는 것으로 옮긴다. */}
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
                  ...ORIGINS.map((value) => ({ value, label: value })),
                ]}
                value={origin || ALL_OPTION}
                onChange={(value) => updateSearchParams({ origin: value === ALL_OPTION ? null : value })}
              />
              <Selector
                label="적합성 등급"
                size="sm"
                options={[
                  { value: ALL_OPTION, label: "전체" },
                  ...GRADE_FILTER_VALUES.map((value) => ({ value, label: value })),
                ]}
                value={gradeFilter || ALL_OPTION}
                onChange={(value) => updateSearchParams({ grade: value === ALL_OPTION ? null : value })}
              />
              {/* 자동 준비는 서버 질의 인자다 — 보기 건수와 같은 전체 집합을 좀힌다. */}
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
              {/* 추적 결정 대기는 서버 질의 인자가 없어 불러온 페이지만 좀힌다. */}
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
              {/* 정렬은 사업 추적과 같은 자리(상세 필터 안 Selector)로 옛겼다. 접혀
                  있어도 지금 어떤 순서인지는 목록 머리가 글자로 밝힌다. */}
              <Selector
                label="표시 순서"
                size="sm"
                options={SORT_OPTIONS.map(({ value, label }) => ({ value, label }))}
                value={sort}
                onChange={(value) => updateSearchParams({ sort: value === "published" ? null : value })}
              />
            </WorkspaceFilterAdvanced>
          ) : null}
        </WorkspaceFilterBar>

        {result.isPending ? (
          <div className="pre-specs-loading" role="status" aria-live="polite">사전규격 목록을 불러오는 중입니다.</div>
        ) : null}
        {result.isError ? (
          <EmptyState
            tone="error"
            title="사전규격 목록을 불러오지 못했습니다."
            description="사전규격 API 응답을 확인할 수 없습니다."
            action={{ label: "다시 시도", onClick: () => { void result.refetch(); } }}
          />
        ) : null}

        {result.isSuccess ? (
          <SplitWorkspace className="pre-specs-split-workspace">
            <section className="review-split-list pre-specs-list-pane" aria-label="사전규격 목록">
              <header className="pre-specs-list-head">
                <strong>
                  사전규격 목록 <span className="mono tabular-nums">{items.length}</span>건
                </strong>
                {/* 정렬은 상세 필터 안에 있어 접히면 보이지 않는다. 지금 어떤
                    순서로 줄 세웠는지는 목록 머리가 늘 글자로 밝힌다(대시보드가
                    `/pre-specs?sort=deadline`로 곧장 연결한다). */}
                <span>{viewOf(view).description}{sort === "deadline" ? " · 마감 임박순" : ""}</span>
              </header>
              <div className="pre-specs-list-columns" aria-hidden="true">
                <span>사업명 / 발주기관</span>
                <span>의견 마감</span>
              </div>
              <div
                className="pre-specs-list-scroll"
                ref={listRef}
                onKeyDown={rowKeyboard.onKeyDown}
                onPointerDownCapture={rowKeyboard.onPointerDownCapture}
              >
                {items.length === 0 ? (
                  <EmptyState
                    compact
                    title="조건에 맞는 사전규격이 없습니다."
                    description={emptyDescription()}
                    action={isDefaultView
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
                <span>
                  불러온 {loadedItems.length}건 중 {items.length}건 표시
                  {total > loadedItems.length ? ` · 전체 ${total}건 중 ${offset + 1}–${rangeEnd}` : ""}
                </span>
                {isPartial ? (
                  <span className="pre-specs-list-foot-note">
                    보기 <strong>{viewOf(view).label}</strong>의 서버 집계는 {serverViewCount}건입니다. 이 수는 필터 전체 기준이고 목록은 불러온 페이지 기준이라 서로 다를 수 있습니다.
                    {gradeFilter ? " 등급 필터는 불러온 페이지에만 적용됩니다." : ""}
                    {trackingDecision ? " 추적 결정 필터도 불러온 페이지에만 적용됩니다." : ""}
                  </span>
                ) : null}
              </footer>
            </section>

            <section className="review-split-detail pre-specs-detail-pane" aria-label="선택한 사전규격">
              {selectedItem ? (
                <PreSpecDetail
                  key={selectedItem.notice_pk}
                  item={selectedItem}
                  listSearch={listSearch}
                  trackingDialogOpen={trackingDialogOpen}
                  onTrackingDialogChange={changeTrackingDialog}
                  trackingCloseRequested={trackingCloseRequested}
                  onTrackingCloseCancel={() => setTrackingCloseRequested(false)}
                  onTrackingCloseConfirm={() => {
                    setTrackingCloseRequested(false);
                    setTrackingDialogOpen(false);
                  }}
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
        ) : null}

        {result.isSuccess && total > PAGE_SIZE ? (
          <nav className="pre-specs-pager" aria-label="사전규격 목록 페이지">
            <button
              className="interaction-control interaction-control-primary"
              type="button"
              disabled={offset === 0}
              onClick={() => {
                const next = new URLSearchParams(searchParams);
                if (offset - PAGE_SIZE > 0) next.set("offset", String(offset - PAGE_SIZE));
                else next.delete("offset");
                setSearchParams(next, { replace: true });
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
                const next = new URLSearchParams(searchParams);
                next.set("offset", String(offset + PAGE_SIZE));
                setSearchParams(next, { replace: true });
              }}
            >
              다음
            </button>
          </nav>
        ) : null}
      </WorkspaceFrame>

      <Dialog isOpen={scopeDialogOpen} onOpenChange={(open) => { if (!open) setScopeDialogOpen(false); }} purpose="info" width={620}>
        <DialogHeader title="표시 범위" onOpenChange={() => setScopeDialogOpen(false)} />
        <div className="pre-specs-dialog-body">
          <p>
            현재 조건의 서버 전체 건수는 <strong>{total}건</strong>이고, 한 번에 최대 {PAGE_SIZE}건을 불러옵니다.
            지금 화면에는 불러온 {loadedItems.length}건 가운데 {items.length}건이 보입니다.
          </p>
          <ul>
            <li>상단 보기 건수는 서버가 필터 전체에서 센 값(<code className="mono">overview_status_counts</code>)이며 페이지 범위와 등급 필터를 반영하지 않습니다.</li>
            <li>적합성 등급과 <strong>추적 결정 대기</strong> 필터는 서버에 질의 인자가 없어 이미 불러온 페이지만 좁힙니다. <strong>자동 준비 상태</strong>는 서버 필터라 전체 집합을 좁힙니다.</li>
            <li>보기는 상태를 묶어 찾기 위한 탐색 도구입니다. 각 행의 개요 상태·등급·자동 준비·추적 상태는 서버 값 그대로입니다.</li>
            <li>SW 중심 기본 보기는 SW사업대상=Y와 추적 중인 발주계획에 연결된 예외를 함께 남깁니다. 목록의 <strong>추적 예외</strong>는 SW사업대상이 Y가 아니지만 추적 중인 발주계획에 연결된 건이고, 값이 없는 SW사업대상은 <strong>SW 미확인</strong>으로 적습니다.</li>
            <li>추적 상태는 사업기회 연결이 없으면 <strong>사업기회 미연결</strong>, 연결은 있는데 서버 값이 없으면 <strong>미확인</strong>입니다. 사람이 고른 <strong>미선택</strong>과 다릅니다.</li>
            <li>품질 표식 · 참조 실행과 mock 참조는 운영 완료가 아니고, 표식 없음을 미측정으로 바꾸지 않습니다. 선택한 건의 현재 표식은 개요 검토 결과 머리줄에 있습니다.</li>
          </ul>
        </div>
      </Dialog>
    </section>
  );
}
