import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { Button } from "@astryxdesign/core/Button";
import { Selector } from "@astryxdesign/core/Selector";
import { Activity } from "lucide-react";
import { opportunitySearchValid, searchKey } from "../lib/search";
import { DEADLINE_IMMINENT_DAYS, imminentDeadline } from "../components/dashboard/dashboardData";
import { describeDeadlineCountdown } from "../lib/deadline";
import { formatListPrice } from "../lib/format";
import { OpportunityDetail } from "../components/opportunities/OpportunityDetail";
import {
  ACTION_REASON_ORDER,
  actionReasonLabel,
  actionReasonsOf,
  holdReviewText,
  latestConfirmedStage,
  nextCheckNote,
  nextCheckOf,
  primaryAgency,
  primaryLinkFacts,
  trackingMark,
  primaryTitle,
  rowPrimaryAction,
  topActionReason,
  type OpportunityDetailIntent,
} from "../components/opportunities/trackingFlow";
import { DeadlineText, StatusMark } from "../components/common/Marks";
import { RecordTable, type RecordTableColumn } from "../components/common/RecordTable";
import { PageHeaderTabs } from "../components/common/PageHeaderActions";

import { useRowKeyboardNavigation } from "../components/common/useRowKeyboardNavigation";
import { ListPagerControls, SplitWorkspace } from "../components/common/ReviewPrimitives";
import {
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
  formatCount,
} from "../components/common/WorkspaceFilters";
import { Toast } from "../components/common/Toast";
import { useToast } from "../components/common/useToast";
import { useUnsavedGuard } from "../components/common/useUnsavedGuard";
import { api } from "../lib/api";
import { originDescription } from "../lib/opportunity";
import type {
  OpportunityActionReason,
  OpportunityFirstRegisteredStage,
  OpportunityListItem,
  OpportunitySection,
} from "../lib/types";
import "../styles/opportunities-relaxed.css";

/**
 * 사업 추적 (ADR-0046 결정 2, 승인된 시안 `bidops-opportunities-erp-20260907`).
 *
 * 목록의 단위는 회차의 공고가 아니라 누적 사업기회이고, 한 사업기회는 어떤
 * 구역에서도 한 행으로만 나타난다. 구역 판정은 **서버가** 한다
 * (`GET /api/opportunities`의 `section`과 `section_counts`). 화면이 다시
 * 판정하지 않으므로 같은 사업이 두 구역에 나타나지 않는다.
 *
 * 이 화면이 정하는 것은 추적 상태 하나다. 적합성 등급·참여 준비 상태·심층 검토
 * 승인·최종 입찰 Go/No-Go를 대신하지 않는다.
 */

const SECTIONS: OpportunitySection[] = ["조치 필요", "추적 중", "보류", "추적 종료", "신규 입찰공고"];
const ACTION_VIEW: OpportunitySection = "조치 필요";
const ALL_VIEW = "전체";
type ViewKey = OpportunitySection | typeof ALL_VIEW;
const VIEWS: ViewKey[] = [...SECTIONS, ALL_VIEW];

const STAGES: OpportunityFirstRegisteredStage[] = ["order_plan", "pre_spec", "bid_notice"];
const SORTS = ["created_at", "tracking_status", "first_registered_stage", "deadline"] as const;
type OpportunitySort = (typeof SORTS)[number];
const SORT_LABELS: Record<OpportunitySort, string> = {
  created_at: "최근 등록순",
  tracking_status: "추적 상태순",
  first_registered_stage: "최초 발견 단계순",
  deadline: "마감 임박순",
};
const PAGE_SIZE = 100;

const DEADLINE_VIEW = "마감 임박";
const DEADLINE_WINDOW_MIN = 1;
const DEADLINE_WINDOW_MAX = 365;

/** 서버 검색 `q`의 허용 길이(spec §7.4). 밖이면 보내지 않는다. */
const SEARCH_MIN = 2;
const SEARCH_MAX = 100;

export function OpportunitiesPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const { toast, showToast, dismissToast } = useToast();
  const [dirty, setDirty] = useState(false);
  const [advanced, setAdvanced] = useState(false);
  const handleDirtyChange = useCallback((next: boolean) => setDirty(next), []);
  /** ↑↓ 키 리스너와 행 탐색의 범위. 표의 스크롤 영역이 모든 행을 담는다. */
  const listRef = useRef<HTMLDivElement>(null);
  /** ↑↓가 페이지 경계를 넘길 때 새 페이지에서 설 자리. `applyParams`·`changeOffset`이 비운다. */
  const boundaryLandingRef = useRef<{ offset: number; direction: "next" | "previous" } | null>(null);

  // 목록은 구역·필터·정렬·선택을 검색 인자로 옮긴다. 그 이동은 route를 떠나는 것이
  // 아니므로 blocker 범위를 `pathname`으로 두고 아래에서 각자의 문구로 확인한다.
  const guard = useUnsavedGuard(dirty, {
    blockSpaNavigation: true,
    scope: "pathname",
    title: "사업 추적 목록을 떠나요",
    message: "저장하지 않은 입력이 있어요. 지금 이동하면 사라지며 저장된 추적 상태와 연결은 바뀌지 않아요.",
  });

  const requestedView = searchParams.get("section");
  const view: ViewKey = VIEWS.includes(requestedView as ViewKey) ? (requestedView as ViewKey) : "조치 필요";
  const requestedStage = searchParams.get("first_registered_stage");
  const stage = STAGES.includes(requestedStage as OpportunityFirstRegisteredStage)
    ? (requestedStage as OpportunityFirstRegisteredStage)
    : null;
  const requestedSort = searchParams.get("sort");
  const sort: OpportunitySort = SORTS.includes(requestedSort as OpportunitySort)
    ? (requestedSort as OpportunitySort)
    : "created_at";
  const requestedWindow = Number(searchParams.get("deadline_within_days") ?? "");
  const deadlineWithinDays = Number.isInteger(requestedWindow)
    && requestedWindow >= DEADLINE_WINDOW_MIN
    && requestedWindow <= DEADLINE_WINDOW_MAX
    ? requestedWindow
    : null;
  const requestedOffset = Number(searchParams.get("offset") ?? "0");
  const offset = Number.isInteger(requestedOffset) && requestedOffset >= 0 ? requestedOffset : 0;
  // 사유 칩은 `조치 필요` 구역 안의 필터다. 다른 구역의 주소에 남아 있어도 보내지 않는다.
  const requestedReason = searchParams.get("reason");
  const reason: OpportunityActionReason | null = view === ACTION_VIEW && ACTION_REASON_ORDER.includes(requestedReason as OpportunityActionReason)
    ? (requestedReason as OpportunityActionReason)
    : null;
  const rawSearch = searchParams.get("q") ?? "";
  const search = searchKey(rawSearch) ? rawSearch : null;
  const invalidUrlSearch = search !== null && !opportunitySearchValid(search);
  const [searchText, setSearchText] = useState(rawSearch);
  const [searchError, setSearchError] = useState(false);

  const list = useQuery({
    queryKey: ["opportunities", view, stage, sort, reason, deadlineWithinDays, searchKey(search), offset],
    queryFn: ({ signal }) =>
      api.getOpportunities(
        {
          section: view === ALL_VIEW ? null : view,
          first_registered_stage: stage,
          reason,
          deadline_within_days: deadlineWithinDays,
          q: search,
          sort,
          limit: PAGE_SIZE,
          offset,
        },
        { signal },
      ),
    enabled: !invalidUrlSearch,
  });

  const rows = useMemo(() => list.data?.items ?? [], [list.data]);
  const total = list.data?.total ?? 0;
  const counts = list.data?.section_counts ?? null;
  const reasonCounts = list.data?.action_reason_counts ?? null;
  const undecided = counts?.["미결정"] ?? 0;
  const allCount = counts ? Object.values(counts).reduce((sum, value) => sum + value, 0) : 0;
  const pagerView = deadlineWithinDays !== null ? "마감 임박" : reason ? actionReasonLabel(reason) : view;
  const pagerDescription = counts && allCount !== total ? `${pagerView} ${formatCount(total)}건` : pagerView;

  const selectedParam = Number(searchParams.get("selected") ?? "");
  /**
   * 레코드·다른 화면에서 `?selected=<id>`로 들어온 사업기회는 지금 구역·페이지에 행이 없어도 그
   * 사업기회를 연다(설계고도화안 C-3) — 첫 행으로 조용히 바꾸지 않는다. 진입 뒤 사람이 행·필터를
   * 바꾸면 그 규칙(지금 목록의 행)으로 돌아간다.
   */
  const entrySelectedRef = useRef<number | null>(Number.isInteger(selectedParam) && selectedParam > 0 ? selectedParam : null);
  const entrySelected = entrySelectedRef.current !== null && entrySelectedRef.current === selectedParam ? selectedParam : null;
  const selectedId = rows.some((item) => item.id === selectedParam) ? selectedParam : entrySelected ?? rows[0]?.id ?? null;
  const returnSearch = searchParams.toString();

  function applyParams(
    changes: Record<string, string | null>,
    confirm: { title: string; message: string; confirmLabel: string },
    onApplied?: () => void,
  ) {
    guard.confirmDiscard(() => {
      // 필터·검색·구역이 바뀌면 사람이 요청한 적 없는 경계 착지는 더 이상 유효하지 않다.
      boundaryLandingRef.current = null;
      const next = new URLSearchParams(searchParams);
      for (const [key, value] of Object.entries(changes)) {
        if (value) next.set(key, value);
        else next.delete(key);
      }
      next.delete("offset");
      next.delete("selected");
      setSearchParams(next, { replace: true });
      onApplied?.();
    }, confirm);
  }

  const changeFilters = (changes: Record<string, string | null>) =>
    applyParams(changes, {
      title: "목록을 바꿔요",
      message: "목록을 바꾸면 열려 있던 사업기회가 닫히고 저장하지 않은 입력이 사라져요.",
      confirmLabel: "저장하지 않고 목록 바꾸기",
    });
  const changeFilter = (key: string, value: string | null) => changeFilters({ [key]: value });

  function applySearch(nextDraft: string) {
    const next = searchKey(nextDraft) ? nextDraft : null;
    if (next && !opportunitySearchValid(next)) {
      setSearchError(true);
      return;
    }
    setSearchError(false);
    if (searchKey(next) === searchKey(rawSearch)) {
      const params = new URLSearchParams(searchParams);
      if (next) params.set("q", next);
      else params.delete("q");
      setSearchParams(params, { replace: true });
      setSearchText(next ?? "");
      return;
    }
    applyParams({ q: next }, {
      title: "목록을 바꿔요",
      message: "검색어를 적용하면 열려 있던 사업기회가 닫히고 저장하지 않은 입력이 사라져요.",
      confirmLabel: "저장하지 않고 검색",
    }, () => setSearchText(next ?? ""));
  }
  useEffect(() => { setSearchText(rawSearch); setSearchError(false); }, [rawSearch]);
  // URL로 들어온 invalid q는 그 값을 그대로 보여 주되, 사용자가 draft를 고치기
  // 시작하면 이전 URL 오류를 계속 붙잡지 않는다. Enter로 다시 invalid를 적용한 경우는
  // `searchError`가 현재 draft의 오류를 소유한다.
  const showSearchError = (invalidUrlSearch && searchKey(searchText) === searchKey(rawSearch)) || searchError;

  const emptyActionQueue = view === ACTION_VIEW && !search && !stage && !reason && deadlineWithinDays === null && offset === 0 && list.data?.total === 0;
  const newBidCount = counts?.["신규 입찰공고"] ?? 0;

  const resetFilters = () => {
    applyParams({ section: null, first_registered_stage: null, sort: null, q: null, reason: null, deadline_within_days: null }, {
      title: "필터를 초기화해요",
      message: "필터를 초기화하면 열려 있던 사업기회가 닫히고 저장하지 않은 입력이 사라져요.",
      confirmLabel: "저장하지 않고 초기화",
    }, () => setSearchText(""));
  };

  function changeOffset(nextOffset: number, onApplied?: () => void) {
    guard.confirmDiscard(() => {
      boundaryLandingRef.current = null;
      const next = new URLSearchParams(searchParams);
      next.set("offset", String(nextOffset));
      next.delete("selected");
      setSearchParams(next, { replace: true });
      onApplied?.();
    }, {
      title: "목록 페이지를 옮겨요",
      message: "페이지를 옮기면 열려 있던 사업기회가 닫히고 저장하지 않은 입력이 사라져요.",
      confirmLabel: "저장하지 않고 페이지 이동",
    });
  }

  // 행의 주 행동은 그 사업기회를 열고 상세의 해당 자리(확인 사항·후보 대화상자·추적
  // 상태 대화상자)를 연다. 같은 행을 다시 눌러도 다시 열리도록 요청마다 번호를 바꾼다.
  const [intent, setIntent] = useState<{ id: number; action: OpportunityDetailIntent; nonce: number } | null>(() => (
    // 레코드의 `확인 항목 답변` 링크(`?selected=<id>&detail=checks`)는 그 사업기회의 확인 사항을 연다.
    entrySelectedRef.current !== null && searchParams.get("detail") === "checks"
      ? { id: entrySelectedRef.current, action: { kind: "checks" }, nonce: 0 }
      : null
  ));
  const intentNonce = useRef(0);
  function runRowAction(item: OpportunityListItem) {
    const action = rowPrimaryAction(item);
    if (!action) return;
    const open = () => {
      intentNonce.current += 1;
      setIntent({ id: item.id, action: action.intent, nonce: intentNonce.current });
    };
    if (item.id === selectedId) {
      open();
      return;
    }
    guard.confirmDiscard(() => {
      const next = new URLSearchParams(searchParams);
      next.set("selected", String(item.id));
      setSearchParams(next, { replace: true });
      open();
    }, {
      title: "다른 사업기회를 열어요",
      message: "저장하지 않은 입력은 이 사업기회를 닫으면 사라져요.",
    });
  }

  function selectRow(id: number) {
    if (id === selectedId) return;
    guard.confirmDiscard(() => {
      const next = new URLSearchParams(searchParams);
      next.set("selected", String(id));
      setSearchParams(next, { replace: true });
    }, {
      title: "다른 사업기회를 열어요",
      message: "저장하지 않은 입력은 이 사업기회를 닫으면 사라져요.",
    });
  }

  /**
   * ↑↓ 목록 이동. 리스너는 목록 표의 스크롤 영역이 지고 `rowProps`는 행이 받는다
   * (발주계획·사전규격과 같은 hook, `useRowKeyboardNavigation`).
   *
   * 경계(현재 페이지의 처음·끝)는 hook이 모르므로 화면이 맡는다. 두 방향 모두 `changeOffset`을
   * 거치므로 저장하지 않은 입력이 있으면 이탈 확인이 먼저고, 사람이 취소하면 페이지도 선택도
   * 그대로다. 페이지를 옮기면 `selected`가 지워져 새 페이지의 첫 행이 선택되므로 `next`는
   * hook의 effect가 초점을 옮긴다. `previous`는 마지막 행에 서야 하므로 아래 effect가 데이터가
   * 온 뒤에 선택과 초점을 옮긴다.
   */
  const rowNavigation = useRowKeyboardNavigation<number>({
    containerRef: listRef,
    keys: rows.map((item) => item.id),
    onBoundary: (direction) => {
      if (direction === "next" && offset + PAGE_SIZE >= total) return;
      if (direction === "previous" && offset === 0) return;
      const targetOffset = direction === "next" ? offset + PAGE_SIZE : Math.max(0, offset - PAGE_SIZE);
      changeOffset(targetOffset, () => {
        boundaryLandingRef.current = { offset: targetOffset, direction };
      });
    },
    onSelect: selectRow,
    selectedKey: selectedId,
  });

  useEffect(() => {
    const landing = boundaryLandingRef.current;
    if (!landing || landing.offset !== offset || list.isPending) return;
    boundaryLandingRef.current = null;
    if (landing.direction !== "previous" || rows.length === 0) return;
    // hook의 effect가 이미 새 페이지의 첫 행에 초점을 줬다. ↑로 넘어온 사람이 서야 하는
    // 자리는 마지막 행이므로 선택과 초점을 모두 명시적으로 옮긴다.
    const lastId = rows[rows.length - 1].id;
    const next = new URLSearchParams(searchParams);
    next.set("selected", String(lastId));
    setSearchParams(next, { replace: true });
    requestAnimationFrame(() => {
      listRef.current?.querySelector<HTMLElement>(`[data-row-key="${lastId}"]`)?.focus();
    });
  }, [list.isPending, offset, rows, searchParams, setSearchParams]);

  const now = new Date();
  const columns: RecordTableColumn<OpportunityListItem>[] = [
    {
      key: "business",
      header: "사업명",
      title: primaryTitle,
      titleClassName: "opportunity-row-title opportunity-row-business",
      renderBelow: (item) => {
        const present = actionReasonsOf(item);
        const hold = holdReviewText(item, now);
        const primaryReason = topActionReason(item);
        const nextCheck = nextCheckOf(item);
        const nextNote = nextCheckNote(item);
        const hasCheckChip = primaryReason !== null && nextCheck.key !== "tracking_decision";
        const chips = ACTION_REASON_ORDER.filter((code) => present.includes(code));
        // 모르는 사유 코드는 감추지 않고 뒤에 그대로 붙인다.
        const unknown = present.filter((code) => !ACTION_REASON_ORDER.includes(code));
        const milestone = deadlineWithinDays === null ? primaryLinkFacts(item)?.milestone : null;
        return (
          <>
            <div className="opportunity-row-reasons-line">
              {chips.length + unknown.length > 0 || hold ? (
                <ul aria-label="조치 사유" className="opportunity-row-reasons">
                  {[...chips, ...unknown].map((code) => (
                    <li key={code}>
                      <StatusMark mark={{
                        label: code === "hold_overdue" && hold ? hold
                          : hasCheckChip && code === primaryReason ? nextCheck.label : actionReasonLabel(code),
                        tone: "warning",
                      }} />
                    </li>
                  ))}
                  {hold && !present.includes("hold_overdue") ? (
                    <li className="record-table-note opportunity-row-hold">{hold}</li>
                  ) : null}
                </ul>
              ) : null}
              <span className="record-table-note opportunity-row-next-note">
                {hasCheckChip ? nextNote : `${nextCheck.label} · ${nextNote}`}
              </span>
            </div>
            <div className="record-table-note opportunity-row-meta">
              {latestConfirmedStage(item.links)}
              {milestone ? <span className="opportunity-row-milestone"> · {milestone}</span> : null}
            </div>
          </>
        );
      },
    },
    {
      key: "agency",
      header: "발주기관",
      width: 60,
      grow: true,
      ellipsis: true,
      className: "opportunity-row-agency",
      renderCell: primaryAgency,
    },
    {
      key: "budget",
      header: "금액",
      width: 108,
      numeric: true,
      className: "opportunity-row-budget",
      renderCell: (item) => {
        const facts = primaryLinkFacts(item);
        if (!facts) return "금액 미확인";
        if (facts.budgetAmount === null) return facts.budget;
        const price = formatListPrice(facts.budgetAmount);
        return <span title={price.exact}>{price.label}</span>;
      },
    },
    {
      key: "tracking",
      header: "추적 상태",
      width: 66,
      className: "opportunity-row-status",
      renderCell: (item) => <StatusMark mark={trackingMark(item.tracking_status)} />,
    },
    {
      key: "deadline",
      header: "다음 마감",
      width: 108,
      className: "opportunity-row-deadline",
      renderCell: (item) => {
        const due = imminentDeadline(item, now.getTime());
        const countdown = describeDeadlineCountdown(due?.deadlineAt);
        return (
          <>
            {due && countdown ? <span className="record-table-note record-table-subline">{due.kind}{" "}</span> : null}
            <DeadlineText text={countdown?.label ?? "마감 미확인"} urgency={countdown?.urgency ?? "none"} />
          </>
        );
      },
    },
    {
      key: "next",
      header: "다음 확인",
      width: 62,
      className: "opportunity-next-cell",
      renderCell: (item) => {
        const action = rowPrimaryAction(item);
        return action ? (
          <Button
            className="opportunity-row-action"
            label={action.label}
            onClick={() => runRowAction(item)}
            size="sm"
          />
        ) : null;
      },
    },
  ];

  return (
    <section aria-labelledby="page-title" className="opportunities-page">
      {/* 화면 제목은 상단바가 제목 모드로 그린다(route-meta `opportunities.topbar`).
          페이지에는 `aria-labelledby`가 가리킬 숨긴 제목만 남고, 화면 액션은 상단바
          슬롯으로 간다 — 같은 이름을 세로로 두 번 쓰지 않기 위해서다. */}
      <span className="visually-hidden" id="page-title">사업 추적</span>

      <PageHeaderTabs>
        <WorkspaceFilterBar aria-label="사업 추적 필터">
          <WorkspaceFilterLine>
            {/* 건수는 서버가 센 전체 집합이다. 아직 못 받았으면 0으로 접지 않고
                아예 표시하지 않는다(`count: undefined`). */}
            <WorkspaceViewTabs
              className="opportunity-view-tabs"
              label="추적 구역"
              onChange={(value) => changeFilters(value === DEADLINE_VIEW
                ? { section: ALL_VIEW, reason: null, deadline_within_days: String(DEADLINE_IMMINENT_DAYS), sort: "deadline" }
                : { section: value === ACTION_VIEW ? null : value, reason: null, deadline_within_days: null,
                  ...(deadlineWithinDays !== null && sort === "deadline" ? { sort: null } : {}) })}
              tabs={[...VIEWS.slice(0, 3), DEADLINE_VIEW, ...VIEWS.slice(3)].map((value) => ({
                key: value,
                label: value,
                count: counts && deadlineWithinDays === null && value !== DEADLINE_VIEW
                  ? (value === ALL_VIEW ? allCount : counts[value as OpportunitySection]) : undefined,
              }))}
              value={deadlineWithinDays === null ? view : DEADLINE_VIEW}
            />
          </WorkspaceFilterLine>
          <WorkspaceFilterTools className="opportunity-filter-tools">
            <WorkspaceAdvancedToggle
              visibleLabel="필터"
              activeCount={Number(Boolean(reason)) + Number(Boolean(stage)) + Number(sort !== "created_at")}
              controlsId="opportunity-filter-advanced"
              isOpen={advanced}
              onToggle={() => setAdvanced(!advanced)}
            />
            {/* `q`는 서버 질의 인자다. Enter 또는 지우기 버튼으로 적용한다. */}
            <WorkspaceSearch
              appliedValue={rawSearch}
              className="opportunity-search"
              errorMessage={showSearchError
                ? "검색어는 공백을 정리한 뒤 2~100자여야 해요."
                : null}
              label="사업명·발주기관 검색"
              onChange={(value) => { setSearchText(value); setSearchError(false); }}
              onClear={() => applySearch("")}
              onEnter={() => applySearch(searchText)}
              value={searchText}
            />
          </WorkspaceFilterTools>
          <WorkspaceFilterAdvanced
            isOpen={advanced}
            onClose={() => setAdvanced(false)}
            id="opportunity-filter-advanced" onReset={resetFilters}>
            {view === ACTION_VIEW ? (
              <WorkspaceFilterGroup title="조치 사유">
                <div className="opportunity-reason-filters">
                  {/* 건수는 서버가 사유 필터만 빼고 센 값이다(`action_reason_counts`). 한 사업은
                      여러 사유에 들어가므로 합이 구역 건수와 같지 않다. */}
                  <div aria-label="조치 사유" className="opportunity-reason-chips" role="group">
                    {ACTION_REASON_ORDER.map((code) => {
                      const count = reasonCounts?.[code];
                      const countText = count == null ? null : formatCount(count);
                      return (
                        <Button
                          aria-pressed={reason === code}
                          data-reason={code}
                          key={code}
                          label={countText === null ? actionReasonLabel(code) : `${actionReasonLabel(code)}  ${countText}`}
                          onClick={() => changeFilter("reason", reason === code ? null : code)}
                          size="sm"
                        >
                          <span className="opportunity-reason-chip-label">{actionReasonLabel(code)}</span>
                          {countText === null ? null : <span className="opportunity-reason-chip-count">{countText}</span>}
                        </Button>
                      );
                    })}
                  </div>

                </div>
              </WorkspaceFilterGroup>
            ) : null}
            <WorkspaceFilterGroup title="조회 범위">
              <Selector
                hasClear
                label="최초 발견 단계"
                onChange={(value) => changeFilter("first_registered_stage", value || null)}
                options={STAGES.map((value) => ({ value, label: originDescription(value) }))}
                placeholder="전체"
                size="sm"
                value={stage ?? ""}
              />
            </WorkspaceFilterGroup>
            <WorkspaceFilterGroup title="정렬">
              <Selector
                label="표시 순서"
                onChange={(value) => changeFilter("sort", value === "created_at" ? null : value)}
                options={SORTS.map((value) => ({ value, label: SORT_LABELS[value] }))}
                size="sm"
                value={sort}
              />
            </WorkspaceFilterGroup>
          </WorkspaceFilterAdvanced>

          {/* 마감 창 줄 — 발주계획의 회차 줄과 같은 자리·같은 방식이다(S1). 상세 필터를
              폈는지와 무관하게 그려서, URL로 들어온 창이 조용히 목록을 좁히지 않게 한다. */}
          {deadlineWithinDays === null ? null : (
            <WorkspaceFilterContext className="opportunity-deadline-context">
              <div className="opportunity-filter-context-line">
                <span className="opportunity-deadline-context-label">
                  {deadlineWithinDays}일 이내 마감
                </span>
                <Button
                  label="해제"
                  onClick={() => changeFilter("deadline_within_days", null)}
                  size="sm"
                  variant="ghost"
                />
              </div>
            </WorkspaceFilterContext>
          )}
        </WorkspaceFilterBar>
      </PageHeaderTabs>
      <WorkspaceFrame>
        <SplitWorkspace
          aria-label="사업 추적 목록과 상세"
          className="opportunity-workspace"
          listClassName="opportunity-list-pane"
          listLabel="사업 추적 목록"
          listHeader={(
            <header className="review-list-head opportunity-list-head">
              <p className="opportunity-list-title">사업 추적 목록 · {formatCount(rows.length)}건</p>
              <p className="opportunity-caption">
                {list.isSuccess
                  ? `${view}${reason ? ` · ${actionReasonLabel(reason)}` : ""}${deadlineWithinDays === null ? "" : ` · ${deadlineWithinDays}일 이내 마감`}${search ? ` · 검색 "${search}"` : ""} 전체 ${formatCount(total)}건`
                  : "사업 단위"}
              </p>
            </header>
          )}
          list={(
            <RecordTable
              activeKey={selectedId}
              className="opportunity-table-scroll"
              columns={columns}
              getKey={(item) => item.id}
              label="사업 추적"
              navigation={rowNavigation}
              onActivate={selectRow}
              rowClassName="opportunity-row"
              rows={rows}
              state={invalidUrlSearch ? {
                kind: "error",
                message: { title: "주소의 검색어는 공백을 정리한 뒤 2~100자여야 해요. 검색어를 고치거나 지워 주세요." },
              } : list.isPending ? {
                kind: "loading", label: "사업 목록을 불러오는 중",
              } : list.isError ? {
                kind: "error",
                message: {
                  title: "사업 목록을 불러오지 못했어요",
                  action: { label: "다시 시도", onClick: () => void list.refetch() },
                },
              } : rows.length === 0 ? {
                kind: "empty",
                message: {
                  title: emptyActionQueue ? "오늘 필요한 조치가 없어요" : "조건에 맞는 사업이 없어요",
                  description: emptyActionQueue ? "신규 입찰공고와 전체 사업은 다른 구역에서 볼 수 있어요." : search ? `적용된 검색어 "${search}"와 다른 활성 필터에 맞는 사업이 없어요.`
                    : "다른 구역이나 다음 페이지에 있을 수 있으며, 사업이 없다는 뜻은 아니에요.",
                  action: emptyActionQueue ? (allCount > 0 ? {
                    label: newBidCount ? `신규 입찰공고 ${formatCount(newBidCount)}건 보기` : "전체 사업 보기",
                    onClick: () => changeFilters({ section: newBidCount ? "신규 입찰공고" : ALL_VIEW, reason: null }),
                  } : undefined) : {
                    label: search ? "검색어만 지우기" : "필터 초기화",
                    onClick: search ? () => applySearch("") : resetFilters,
                  },
                },
              } : undefined}
              viewportRef={listRef}
            />
          )}
          listFooter={(
            <>
              {invalidUrlSearch || searchError ? (
                <p className="opportunity-list-notice opportunity-caption">
                  검색어는 공백을 정리한 뒤 {SEARCH_MIN}~{SEARCH_MAX}자여야 해요. {search && !invalidUrlSearch ? `현재 목록은 검색어 "${search}" 결과예요.` : "검색어를 고치거나 지워 주세요."}
                </p>
              ) : null}
              {list.isSuccess && (total > 0 || allCount > 0 || offset > 0) ? (
                <ListPagerControls
                  className="opportunity-pager"
                  label="사업 추적 목록 페이지"
                  offset={offset}
                  onNext={() => changeOffset(offset + PAGE_SIZE)}
                  onPrevious={() => changeOffset(Math.max(0, offset - PAGE_SIZE))}
                  summary={{ overallTotal: counts ? allCount : undefined, description: pagerDescription }}
                  total={total}
                  visibleCount={rows.length}
                />
              ) : null}
            </>
          )}
          detailClassName="opportunity-detail-pane"
          detailLabel="선택한 사업"
          detail={(
            list.isPending ? (
              <div className="opportunity-empty">
                <p>목록을 불러온 뒤 사업 상세를 표시해요.</p>
              </div>
            ) : selectedId !== null ? (
              <OpportunityDetail
                intent={intent?.id === selectedId ? intent : null}
                key={selectedId}
                onDirtyChange={handleDirtyChange}
                onSaved={showToast}
                opportunityId={selectedId}
                returnSearch={returnSearch}
              />
            ) : list.isError || invalidUrlSearch ? (
              <div className="opportunity-empty">
                <h3>선택할 사업이 없어요</h3>
              </div>
            ) : null
          )}
        />
      </WorkspaceFrame>

      {toast ? <Toast message={toast.message} onDismiss={dismissToast} variant={toast.variant} /> : null}
    </section>
  );
}
