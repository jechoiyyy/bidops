import { useCallback, useEffect, useMemo, useRef, useState, type MouseEvent as ReactMouseEvent } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { Button } from "@astryxdesign/core/Button";
import { Dialog, DialogHeader } from "@astryxdesign/core/Dialog";
import { Selector } from "@astryxdesign/core/Selector";
import { Table, pixel, proportional, type TableColumn } from "@astryxdesign/core/Table";
import { Token } from "@astryxdesign/core/Token";
import { Activity } from "lucide-react";
import { opportunitySearchValid, searchKey } from "../lib/search";
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
  primaryTitle,
  rowPrimaryAction,
  type OpportunityDetailIntent,
} from "../components/opportunities/trackingFlow";
import { EmptyState } from "../components/common/EmptyState";
import { PageHeaderActions } from "../components/common/PageHeaderActions";
import { ListPagerControls } from "../components/common/ReviewPrimitives";
import { SkeletonPanel } from "../components/common/Skeleton";
import {
  WorkspaceAdvancedToggle,
  WorkspaceFilterAdvanced,
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
const SORTS = ["created_at", "tracking_status", "first_registered_stage"] as const;
type OpportunitySort = (typeof SORTS)[number];
const SORT_LABELS: Record<OpportunitySort, string> = {
  created_at: "최근 등록순",
  tracking_status: "추적 상태순",
  first_registered_stage: "최초 발견 단계순",
};
const PAGE_SIZE = 100;

/** 서버 검색 `q`의 허용 길이(spec §7.4). 밖이면 보내지 않는다. */
const SEARCH_MIN = 2;
const SEARCH_MAX = 100;

/** Astryx `Table`은 행 type이 index signature를 갖기를 요구한다. 값은 그대로다. */
type OpportunityRow = OpportunityListItem & Record<string, unknown>;

export function OpportunitiesPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const { toast, showToast, dismissToast } = useToast();
  const [dirty, setDirty] = useState(false);
  const [advanced, setAdvanced] = useState(false);
  const [dataDialog, setDataDialog] = useState(false);
  const handleDirtyChange = useCallback((next: boolean) => setDirty(next), []);

  // 목록은 구역·필터·정렬·선택을 검색 인자로 옮긴다. 그 이동은 route를 떠나는 것이
  // 아니므로 blocker 범위를 `pathname`으로 두고 아래에서 각자의 문구로 확인한다.
  const guard = useUnsavedGuard(dirty, {
    blockSpaNavigation: true,
    scope: "pathname",
    title: "사업 추적 목록을 떠납니다",
    message: "저장하지 않은 입력이 있습니다. 지금 이동하면 사라지며 저장된 추적 상태와 연결은 바뀌지 않습니다.",
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
    queryKey: ["opportunities", view, stage, sort, reason, searchKey(search), offset],
    queryFn: ({ signal }) =>
      api.getOpportunities(
        {
          section: view === ALL_VIEW ? null : view,
          first_registered_stage: stage,
          reason,
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

  const selectedParam = Number(searchParams.get("selected") ?? "");
  const selectedId = rows.some((item) => item.id === selectedParam) ? selectedParam : rows[0]?.id ?? null;
  const returnSearch = searchParams.toString();

  function applyParams(
    changes: Record<string, string | null>,
    confirm: { title: string; message: string; confirmLabel: string },
    onApplied?: () => void,
  ) {
    guard.confirmDiscard(() => {
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
      title: "목록을 바꿉니다",
      message: "목록을 바꾸면 열려 있던 사업기회가 닫히고 저장하지 않은 입력이 사라집니다.",
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
      title: "목록을 바꿉니다",
      message: "검색어를 적용하면 열려 있던 사업기회가 닫히고 저장하지 않은 입력이 사라집니다.",
      confirmLabel: "저장하지 않고 검색",
    }, () => setSearchText(next ?? ""));
  }
  useEffect(() => { setSearchText(rawSearch); setSearchError(false); }, [rawSearch]);
  // URL로 들어온 invalid q는 그 값을 그대로 보여 주되, 사용자가 draft를 고치기
  // 시작하면 이전 URL 오류를 계속 붙잡지 않는다. Enter로 다시 invalid를 적용한 경우는
  // `searchError`가 현재 draft의 오류를 소유한다.
  const showSearchError = (invalidUrlSearch && searchKey(searchText) === searchKey(rawSearch)) || searchError;

  const resetFilters = () => {
    applyParams({ section: null, first_registered_stage: null, sort: null, q: null, reason: null }, {
      title: "필터를 초기화합니다",
      message: "필터를 초기화하면 열려 있던 사업기회가 닫히고 저장하지 않은 입력이 사라집니다.",
      confirmLabel: "저장하지 않고 초기화",
    }, () => setSearchText(""));
  };

  function changeOffset(nextOffset: number) {
    guard.confirmDiscard(() => {
      const next = new URLSearchParams(searchParams);
      next.set("offset", String(nextOffset));
      next.delete("selected");
      setSearchParams(next, { replace: true });
    }, {
      title: "목록 페이지를 옮깁니다",
      message: "페이지를 옮기면 열려 있던 사업기회가 닫히고 저장하지 않은 입력이 사라집니다.",
      confirmLabel: "저장하지 않고 페이지 이동",
    });
  }

  // 행의 주 행동은 그 사업기회를 열고 상세의 해당 자리(확인 사항·후보 대화상자·추적
  // 상태 대화상자)를 연다. 같은 행을 다시 눌러도 다시 열리도록 요청마다 번호를 바꾼다.
  const [intent, setIntent] = useState<{ id: number; action: OpportunityDetailIntent; nonce: number } | null>(null);
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
      title: "다른 사업기회를 엽니다",
      message: "저장하지 않은 입력은 이 사업기회를 닫으면 사라집니다.",
    });
  }

  function selectRow(id: number) {
    if (id === selectedId) return;
    guard.confirmDiscard(() => {
      const next = new URLSearchParams(searchParams);
      next.set("selected", String(id));
      setSearchParams(next, { replace: true });
    }, {
      title: "다른 사업기회를 엽니다",
      message: "저장하지 않은 입력은 이 사업기회를 닫으면 사라집니다.",
    });
  }

  const now = new Date();
  const columns: TableColumn<OpportunityRow>[] = [
    {
      key: "business",
      header: "사업명 / 발주기관",
      width: proportional(1),
      renderCell: (item) => {
        const present = actionReasonsOf(item);
        const hold = holdReviewText(item, now);
        const chips = ACTION_REASON_ORDER.filter((code) => present.includes(code));
        // 모르는 사유 코드는 감추지 않고 뒤에 그대로 붙인다.
        const unknown = present.filter((code) => !ACTION_REASON_ORDER.includes(code));
        return (
          <div className="opportunity-row-cell">
            <button
              aria-pressed={item.id === selectedId}
              className="opportunity-row-business"
              onClick={() => selectRow(item.id)}
              type="button"
            >
              <span className="opportunity-row-title">{primaryTitle(item)}</span>
              <span className="opportunity-row-agency">{primaryAgency(item)}</span>
              <span className="opportunity-row-meta">
                <span className="opportunity-caption">{latestConfirmedStage(item.links)}</span>
                <span className="opportunity-caption">·</span>
                <span className="opportunity-caption">{item.tracking_status}</span>
              </span>
            </button>
            {chips.length + unknown.length > 0 || hold ? (
              <ul aria-label="조치 사유" className="opportunity-row-reasons">
                {[...chips, ...unknown].map((code) => (
                  <li key={code}>
                    <Token
                      label={code === "hold_overdue" && hold ? hold : actionReasonLabel(code)}
                      size="sm"
                    />
                  </li>
                ))}
                {hold && !present.includes("hold_overdue") ? (
                  <li className="opportunity-caption opportunity-row-hold">{hold}</li>
                ) : null}
              </ul>
            ) : null}
          </div>
        );
      },
    },
    {
      key: "next",
      header: "다음 확인",
      width: pixel(120),
      renderCell: (item) => {
        const action = rowPrimaryAction(item);
        return (
          <span className="opportunity-next-cell">
            <span className={`opportunity-next-label${item.section === ACTION_VIEW ? " is-action" : ""}`}>
              {nextCheckOf(item).label}
            </span>
            <span className="opportunity-caption">{nextCheckNote(item)}</span>
            {action ? (
              <Button
                className="opportunity-row-action"
                label={action.label}
                onClick={() => runRowAction(item)}
                size="sm"
              />
            ) : null}
          </span>
        );
      },
    },
  ];

  // 행 어디를 눌러도 상세가 열린다. 키보드로 여는 자리는 첫 열의 버튼 하나이며,
  // 이 처리는 포인터 편의만 더한다(버튼·링크를 누른 경우는 그쪽이 처리한다).
  const selectFromRow = (event: ReactMouseEvent<HTMLDivElement>) => {
    const target = event.target as HTMLElement;
    if (target.closest("button, a, input")) return;
    const row = target.closest("tbody tr");
    if (!row?.parentElement) return;
    const index = Array.prototype.indexOf.call(row.parentElement.children, row);
    const item = rows[index];
    if (item) selectRow(item.id);
  };

  return (
    <section aria-labelledby="page-title" className="opportunities-page">
      {/* 화면 제목은 상단바가 제목 모드로 그린다(route-meta `opportunities.topbar`).
          페이지에는 `aria-labelledby`가 가리킬 숨긴 제목만 남고, 화면 액션은 상단바
          슬롯으로 간다 — 같은 이름을 세로로 두 번 쓰지 않기 위해서다. */}
      <h2 className="visually-hidden" id="page-title">사업 추적</h2>
      <PageHeaderActions>
        <div className="opportunity-header-actions">
          <Button
            icon={<Activity />}
            label="목록 기준"
            onClick={() => setDataDialog(true)}
            size="sm"
            variant="ghost"
          />
        </div>
      </PageHeaderActions>

      <WorkspaceFrame>
        <WorkspaceFilterBar aria-label="사업 추적 필터">
          <WorkspaceFilterLine>
            {/* 건수는 서버가 센 전체 집합이다. 아직 못 받았으면 0으로 접지 않고
                아예 표시하지 않는다(`count: undefined`). */}
            <WorkspaceViewTabs
              className="opportunity-view-tabs"
              label="추적 구역"
              onChange={(value) => changeFilters({ section: value === ACTION_VIEW ? null : value, reason: null })}
              tabs={VIEWS.map((value) => ({
                key: value,
                label: value,
                count: counts ? (value === ALL_VIEW ? allCount : counts[value]) : undefined,
              }))}
              value={view}
            />
          </WorkspaceFilterLine>
          <WorkspaceFilterTools className="opportunity-filter-tools">
            <WorkspaceAdvancedToggle
              controlsId="opportunity-filter-advanced"
              isOpen={advanced}
              onToggle={() => setAdvanced(!advanced)}
            />
            {/* `q`는 서버 질의 인자다. Enter 또는 지우기 버튼으로 적용한다. */}
            <WorkspaceSearch
              appliedValue={rawSearch}
              className="opportunity-search"
              errorMessage={showSearchError
                ? "검색어는 공백을 정리한 뒤 2~100자여야 합니다."
                : null}
              label="사업명·발주기관 검색"
              onChange={(value) => { setSearchText(value); setSearchError(false); }}
              onClear={() => applySearch("")}
              onEnter={() => applySearch(searchText)}
              value={searchText}
            />
          </WorkspaceFilterTools>
          {view === ACTION_VIEW ? (
            <WorkspaceFilterContext className="opportunity-reason-filters">
              {/* 건수는 서버가 사유 필터만 빼고 센 값이다(`action_reason_counts`). 한 사업은
                  여러 사유에 들어가므로 합이 구역 건수와 같지 않다. */}
              <div aria-label="조치 사유" className="opportunity-reason-chips" role="group">
                {ACTION_REASON_ORDER.map((code) => {
                  const count = reasonCounts ? reasonCounts[code] ?? null : undefined;
                  const countText = count === undefined ? null : count === null ? "–" : formatCount(count);
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
              <p className="opportunity-caption">
                {reason
                  ? `${actionReasonLabel(reason)} 사유만 봅니다. 구역 건수도 이 사유 기준이며 같은 칩을 다시 누르면 풀립니다.`
                  : "사유 칩을 누르면 그 사유가 있는 사업만 봅니다. 한 사업이 여러 사유에 들어갈 수 있습니다."}
              </p>
            </WorkspaceFilterContext>
          ) : null}
          {advanced ? (
            <WorkspaceFilterAdvanced columns={2} id="opportunity-filter-advanced" onReset={resetFilters}>
              <Selector
                hasClear
                label="최초 발견 단계"
                onChange={(value) => changeFilter("first_registered_stage", value || null)}
                options={STAGES.map((value) => ({ value, label: originDescription(value) }))}
                placeholder="전체"
                size="sm"
                value={stage ?? ""}
              />
              <Selector
                label="표시 순서"
                onChange={(value) => changeFilter("sort", value === "created_at" ? null : value)}
                options={SORTS.map((value) => ({ value, label: SORT_LABELS[value] }))}
                size="sm"
                value={sort}
              />
            </WorkspaceFilterAdvanced>
          ) : null}
        </WorkspaceFilterBar>

        <div aria-label="사업 추적 목록과 상세" className="opportunity-workspace">
          <section aria-label="사업 추적 목록" className="opportunity-list-pane">
            <header className="opportunity-list-head">
              <p className="opportunity-list-title">사업 추적 목록 · {formatCount(rows.length)}건</p>
              <p className="opportunity-caption">
                {list.isSuccess
                  ? `${view}${reason ? ` · ${actionReasonLabel(reason)}` : ""}${search ? ` · 검색 "${search}"` : ""} 전체 ${formatCount(total)}건`
                  : "사업 단위"}
              </p>
            </header>
            <div className="opportunity-table-scroll" onClick={selectFromRow} role="presentation">
              {invalidUrlSearch ? (
                <div className="opportunity-empty">
                  <p role="alert">주소의 검색어는 공백을 정리한 뒤 2~100자여야 합니다. 검색어를 고치거나 지우십시오.</p>
                </div>
              ) : list.isPending ? (
                <SkeletonPanel label="사업 목록을 불러오는 중" lines={5} />
              ) : list.isError ? (
                <div className="opportunity-empty">
                  <EmptyState
                    compact
                    tone="error"
                    title="사업 목록을 불러오지 못했습니다."
                    action={{ label: "다시 시도", onClick: () => void list.refetch() }}
                  />
                </div>
              ) : rows.length === 0 ? (
                <div className="opportunity-empty">
                  <EmptyState
                    compact
                    title="조건에 맞는 사업이 없습니다"
                    description={search ? `적용된 검색어 "${search}"와 다른 활성 필터에 맞는 사업이 없습니다.`
                      : "다른 구역이나 다음 페이지에 있을 수 있으며, 사업이 없다는 뜻은 아닙니다."}
                    action={{
                      label: search ? "검색어만 지우기" : "필터 초기화",
                      onClick: search ? () => applySearch("") : resetFilters,
                    }}
                  />
                </div>
              ) : (
                <Table
                  columns={columns}
                  data={rows as OpportunityRow[]}
                  density="compact"
                  dividers="rows"
                  hasHover
                  idKey="id"
                  verticalAlign="top"
                />
              )}
            </div>
            <footer className="opportunity-list-foot">
              <p className="opportunity-caption">
                {invalidUrlSearch
                  ? "검색어 오류로 목록을 조회하지 않았습니다."
                  : `서버 ${formatCount(total)}건 중 ${formatCount(rows.length)}건 표시${search ? ` · 검색어 "${search}"는 서버가 페이지를 나누기 전에 적용합니다` : ""}`}
              </p>
              {invalidUrlSearch || searchError ? (
                <p className="opportunity-caption">
                  검색어는 공백을 정리한 뒤 {SEARCH_MIN}~{SEARCH_MAX}자여야 합니다. {search && !invalidUrlSearch ? `현재 목록은 검색어 "${search}" 결과입니다.` : "검색어를 고치거나 지우십시오."}
                </p>
              ) : null}
              {undecided > 0 ? (
                <p className="opportunity-caption">
                  구역이 정해지지 않은 미결정 {formatCount(undecided)}건은 전체에서만 보입니다.
                </p>
              ) : null}
              {/* 페이저는 목록 pane 안쪽 바닥이고 발주계획·사전규격과 같은 공용 부품을
                  쓴다(명세 §2.2, U3). 한 쪽뿐이어도 줄은 남기고 단추만 끈다 — 그래서
                  "뒤에 N건이 더 있습니다" 문단은 없앴다. 페이저의 `1–100 / 1,234`가
                  같은 사실을 말한다. */}
              {list.isSuccess ? (
                <ListPagerControls
                  className="opportunity-pager"
                  label="사업 추적 목록 페이지"
                  offset={offset}
                  onNext={() => changeOffset(offset + PAGE_SIZE)}
                  onPrevious={() => changeOffset(Math.max(0, offset - PAGE_SIZE))}
                  total={total}
                  visibleCount={rows.length}
                />
              ) : null}
            </footer>
          </section>

          <section aria-label="선택한 사업" className="opportunity-detail-pane">
            {list.isPending ? (
              <div className="opportunity-empty">
                <p>목록을 불러온 뒤 사업 상세를 표시합니다.</p>
              </div>
            ) : selectedId === null ? (
              <div className="opportunity-empty">
                <h3>선택할 사업이 없습니다</h3>
              </div>
            ) : (
              <OpportunityDetail
                intent={intent?.id === selectedId ? intent : null}
                key={selectedId}
                onDirtyChange={handleDirtyChange}
                onSaved={showToast}
                opportunityId={selectedId}
                returnSearch={returnSearch}
              />
            )}
          </section>
        </div>
      </WorkspaceFrame>

      <Dialog
        isOpen={dataDialog}
        maxHeight="90dvh"
        onOpenChange={(next) => setDataDialog(next)}
        padding={6}
        purpose="info"
        width="calc(var(--spacing-12) * 13)"
      >
        <div className="opportunity-dialog-body">
          <DialogHeader title="이 목록의 기준" onOpenChange={(next) => setDataDialog(next)} />
          <p>
            구역 건수는 서버가 센 수이며 <strong>구역 조건만 빼고</strong> 검색어·최초 발견 단계·사유 필터를 반영합니다.
            사유 칩 건수는 사유 필터만 빼고 센 수이고, 한 사업이 여러 사유에 들어갈 수 있어 합이 구역 건수와 같지
            않습니다. 목록은 한 번에 최대 {formatCount(PAGE_SIZE)}건을 받으며, 검색어는 서버가 페이지를 나누기 전에
            적용합니다.
          </p>
          <p>
            구역은 서버가 정합니다. 사람이 고른 추적 상태와 구역은 서로 다른 축이며, 한 사업기회는 어느 구역에서도 한
            행으로만 나타납니다. 구역이 정해지지 않은 건은 <strong>미결정</strong>으로 세고 전체에서만 보입니다.
          </p>
          <p>
            연결 현황의 체크는 <strong>연결 확정</strong>을 뜻하며 분석 완료나 입찰 참여 승인이 아닙니다.
            <strong> 검색 미확인</strong>은 이름 검색으로 찾지 못했다는 뜻이고 레코드가 없다는 뜻이 아닙니다. 입찰 변경
            비교 결과가 없으면 계산 대기이며, 화면이 결과를 만들어 내지 않습니다.
          </p>
          <p className="opportunity-caption">
            현재 구역 {view} · 서버 {formatCount(total)}건 중 {formatCount(rows.length)}건을 받았습니다.
            {counts
              ? ` 구역 건수 — ${SECTIONS.map((key) => `${key} ${formatCount(counts[key])}`).join(" · ")} · 미결정 ${formatCount(undecided)}`
              : " 구역 건수를 아직 받지 못했습니다."}
          </p>
          <div className="opportunity-dialog-actions">
            <Button label="닫기" onClick={() => setDataDialog(false)} variant="primary" />
          </div>
        </div>
      </Dialog>

      {toast ? <Toast message={toast.message} onDismiss={dismissToast} variant={toast.variant} /> : null}
    </section>
  );
}

/**
 * 단독 상세 route. 목록의 구역·필터·정렬·페이지 문맥을 그대로 유지한 채 사업기회
 * 하나만 연다. 분할 화면과 같은 상세 컴포넌트를 쓴다.
 */
export function OpportunityDetailPage() {
  const { opportunityId: opportunityIdParam } = useParams();
  const [searchParams] = useSearchParams();
  const { toast, showToast, dismissToast } = useToast();
  const [dirty, setDirty] = useState(false);
  const opportunityId = Number(opportunityIdParam);
  const validOpportunityId = Number.isInteger(opportunityId) && opportunityId > 0;
  const handleDirtyChange = useCallback((next: boolean) => setDirty(next), []);
  useUnsavedGuard(dirty, {
    blockSpaNavigation: true,
    title: "사업 추적 상세를 떠납니다",
    message: "저장하지 않은 입력이 있습니다. 지금 이동하면 사라지며 저장된 추적 상태와 연결은 바뀌지 않습니다.",
  });
  const returnSearch = searchParams.toString();

  return (
    <section aria-labelledby="page-title" className="opportunities-page opportunity-detail-page">
      <header className="opportunity-page-header">
        <h2 id="page-title">사업 추적 상세{validOpportunityId ? ` #${opportunityId}` : ""}</h2>
        <Link className="opportunity-linked-link" to={{ pathname: "/opportunities", search: returnSearch }}>
          목록으로 →
        </Link>
      </header>

      <div className="opportunity-standalone-pane">
        {validOpportunityId ? (
          <OpportunityDetail
            onDirtyChange={handleDirtyChange}
            onSaved={showToast}
            opportunityId={opportunityId}
            returnSearch={returnSearch}
          />
        ) : (
          <div className="opportunity-empty">
            <h3>사업기회 식별자가 올바르지 않습니다</h3>
          </div>
        )}
      </div>

      {toast ? <Toast message={toast.message} onDismiss={dismissToast} variant={toast.variant} /> : null}
    </section>
  );
}
