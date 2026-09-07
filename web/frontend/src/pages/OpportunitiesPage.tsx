import { useCallback, useEffect, useMemo, useState, type MouseEvent as ReactMouseEvent } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { Button } from "@astryxdesign/core/Button";
import { Dialog, DialogHeader } from "@astryxdesign/core/Dialog";
import { Selector } from "@astryxdesign/core/Selector";
import { Table, pixel, proportional, type TableColumn } from "@astryxdesign/core/Table";
import { TextInput } from "@astryxdesign/core/TextInput";
import { Activity, ListFilter, Search } from "lucide-react";
import { OpportunityDetail } from "../components/opportunities/OpportunityDetail";
import {
  latestConfirmedStage,
  nextCheckNote,
  nextCheckOf,
  primaryAgency,
  primaryTitle,
} from "../components/opportunities/trackingFlow";
import { Toast } from "../components/common/Toast";
import { useToast } from "../components/common/useToast";
import { useUnsavedGuard } from "../components/common/useUnsavedGuard";
import { api } from "../lib/api";
import { originDescription } from "../lib/opportunity";
import type {
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

const SECTIONS: OpportunitySection[] = ["조치 필요", "추적 중", "보류", "추적 종료"];
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

/** Astryx `Table`은 행 type이 index signature를 갖기를 요구한다. 값은 그대로다. */
type OpportunityRow = OpportunityListItem & Record<string, unknown>;

function countLabel(value: number): string {
  return value.toLocaleString("ko-KR");
}

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
  const search = (searchParams.get("q") ?? "").trim();
  const [searchText, setSearchText] = useState(search);
  useEffect(() => setSearchText(search), [search]);

  const list = useQuery({
    queryKey: ["opportunities", view, stage, sort, offset],
    queryFn: ({ signal }) =>
      api.getOpportunities(
        {
          section: view === ALL_VIEW ? null : view,
          first_registered_stage: stage,
          sort,
          limit: PAGE_SIZE,
          offset,
        },
        { signal },
      ),
  });

  const received = useMemo(() => list.data?.items ?? [], [list.data]);
  const total = list.data?.total ?? 0;
  const counts = list.data?.section_counts ?? null;
  const undecided = counts?.["미결정"] ?? 0;
  const allCount = counts ? Object.values(counts).reduce((sum, value) => sum + value, 0) : 0;

  // 검색은 서버 질의 인자가 없어 **이미 받은 페이지 안에서만** 걸린다. 구역 건수는
  // 필터 이전 전체 집합이므로 두 수를 같은 뜻으로 읽히게 두지 않는다. 입력은 바로
  // 목록을 좁히고, 주소의 `q`는 Enter로 확정해 공유 가능한 링크로 남는다.
  const applied = searchText.trim();
  const rows = useMemo(() => {
    if (!applied) return received;
    const needle = applied.toLowerCase();
    return received.filter((item) => `${primaryTitle(item)} ${primaryAgency(item)}`.toLowerCase().includes(needle));
  }, [received, applied]);

  const selectedParam = Number(searchParams.get("selected") ?? "");
  const selectedId = rows.some((item) => item.id === selectedParam) ? selectedParam : rows[0]?.id ?? null;
  const returnSearch = searchParams.toString();

  function applyParams(changes: Record<string, string | null>, confirm: { title: string; message: string; confirmLabel: string }) {
    guard.confirmDiscard(() => {
      const next = new URLSearchParams(searchParams);
      for (const [key, value] of Object.entries(changes)) {
        if (value) next.set(key, value);
        else next.delete(key);
      }
      next.delete("offset");
      next.delete("selected");
      setSearchParams(next, { replace: true });
    }, confirm);
  }

  const changeFilter = (key: string, value: string | null) =>
    applyParams({ [key]: value }, {
      title: "목록을 바꿉니다",
      message: "목록을 바꾸면 열려 있던 사업기회가 닫히고 저장하지 않은 입력이 사라집니다.",
      confirmLabel: "저장하지 않고 목록 바꾸기",
    });

  const resetFilters = () => {
    setSearchText("");
    applyParams({ section: null, first_registered_stage: null, sort: null, q: null }, {
      title: "필터를 초기화합니다",
      message: "필터를 초기화하면 열려 있던 사업기회가 닫히고 저장하지 않은 입력이 사라집니다.",
      confirmLabel: "저장하지 않고 초기화",
    });
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

  const columns: TableColumn<OpportunityRow>[] = [
    {
      key: "business",
      header: "사업명 / 발주기관",
      width: proportional(1),
      renderCell: (item) => (
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
      ),
    },
    {
      key: "next",
      header: "다음 확인",
      width: pixel(105),
      renderCell: (item) => (
        <span className="opportunity-next-cell">
          <span className={`opportunity-next-label${item.section === "조치 필요" ? " is-action" : ""}`}>
            {nextCheckOf(item).label}
          </span>
          <span className="opportunity-caption">{nextCheckNote(item)}</span>
        </span>
      ),
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
      <header className="opportunity-page-header">
        <h2 id="page-title">사업 추적</h2>
        <Button
          icon={<Activity />}
          label="데이터 현황"
          onClick={() => setDataDialog(true)}
          size="sm"
          variant="ghost"
        />
      </header>

      <section aria-label="사업 추적 필터" className="opportunity-filters">
        <div className="opportunity-filter-line">
          <div aria-label="추적 구역" className="opportunity-view-tabs" role="group">
            {VIEWS.map((value) => (
              <Button
                aria-pressed={view === value}
                key={value}
                label={counts ? `${value}  ${countLabel(value === ALL_VIEW ? allCount : counts[value])}` : value}
                onClick={() => changeFilter("section", value === "조치 필요" ? null : value)}
                size="sm"
              />
            ))}
          </div>
          <div className="opportunity-filter-end">
            <TextInput
              className="opportunity-search"
              hasClear
              isLabelHidden
              label="사업명·발주기관 검색"
              onChange={setSearchText}
              onEnter={() => changeFilter("q", searchText.trim() || null)}
              placeholder="사업명·발주기관 검색"
              size="sm"
              startIcon={Search}
              value={searchText}
            />
            <Button
              aria-expanded={advanced}
              icon={<ListFilter />}
              isIconOnly
              label="상세 필터"
              onClick={() => setAdvanced(!advanced)}
              size="sm"
            />
          </div>
        </div>
        {advanced ? (
          <div className="opportunity-filter-advanced">
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
            <Button label="필터 초기화" onClick={resetFilters} size="sm" />
          </div>
        ) : null}
      </section>

      <div aria-label="사업 추적 목록과 상세" className="opportunity-workspace">
        <section aria-label="사업 추적 목록" className="opportunity-list-pane">
          <header className="opportunity-list-head">
            <p className="opportunity-list-title">사업 추적 목록 · {countLabel(rows.length)}건</p>
            <p className="opportunity-caption">
              {list.isSuccess ? `${view} 전체 ${countLabel(view === ALL_VIEW ? allCount : total)}건` : "사업 단위"}
            </p>
          </header>
          <div className="opportunity-table-scroll" onClick={selectFromRow} role="presentation">
            {list.isPending ? (
              <div className="opportunity-empty">
                <p role="status">사업 목록을 불러오는 중…</p>
              </div>
            ) : list.isError ? (
              <div className="opportunity-empty">
                <p role="alert">사업 목록을 불러오지 못했습니다.</p>
                <Button label="다시 불러오기" onClick={() => void list.refetch()} />
              </div>
            ) : rows.length === 0 ? (
              <div className="opportunity-empty">
                <Search aria-hidden="true" />
                <h3>조건에 맞는 사업이 없습니다</h3>
                <p className="opportunity-caption">
                  다른 구역이나 다음 페이지에 있을 수 있으며, 사업이 없다는 뜻은 아닙니다.
                </p>
                <Button label="필터 초기화" onClick={resetFilters} />
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
              불러온 {countLabel(received.length)}건 기준 · {countLabel(rows.length)}건 표시
              {applied ? ` · 검색어 "${applied}"는 불러온 목록 안에서만 걸립니다` : ""}
            </p>
            {undecided > 0 ? (
              <p className="opportunity-caption">
                구역이 정해지지 않은 미결정 {countLabel(undecided)}건은 전체에서만 보입니다.
              </p>
            ) : null}
            {total > offset + received.length ? (
              <p className="opportunity-caption">
                뒤에 {countLabel(total - offset - received.length)}건이 더 있습니다.
              </p>
            ) : null}
            {total > PAGE_SIZE ? (
              <nav aria-label="목록 페이지" className="opportunity-check-actions">
                <Button
                  isDisabled={offset === 0}
                  label="이전"
                  onClick={() => changeOffset(Math.max(0, offset - PAGE_SIZE))}
                  size="sm"
                />
                <span className="opportunity-caption">
                  {offset + 1}–{Math.min(offset + received.length, total)} / {countLabel(total)}
                </span>
                <Button
                  isDisabled={offset + PAGE_SIZE >= total}
                  label="다음"
                  onClick={() => changeOffset(offset + PAGE_SIZE)}
                  size="sm"
                />
              </nav>
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
              key={selectedId}
              onDirtyChange={handleDirtyChange}
              onSaved={showToast}
              opportunityId={selectedId}
              returnSearch={returnSearch}
            />
          )}
        </section>
      </div>

      <Dialog
        isOpen={dataDialog}
        maxHeight="90dvh"
        onOpenChange={(next) => setDataDialog(next)}
        padding={6}
        purpose="info"
        width="calc(var(--spacing-12) * 13)"
      >
        <div className="opportunity-dialog-body">
          <DialogHeader title="데이터 현황" onOpenChange={(next) => setDataDialog(next)} />
          <p>
            구역 건수는 서버가 센 <strong>전체 집합</strong>의 수입니다. 목록은 한 번에 최대 {countLabel(PAGE_SIZE)}건을
            받으며, 검색어는 서버 질의 인자가 없어 <strong>이미 받은 페이지 안에서만</strong> 걸립니다. 두 수가 다를 수
            있고 같은 뜻이 아닙니다.
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
            현재 구역 {view} · 서버 {countLabel(total)}건 중 {countLabel(received.length)}건을 받았습니다.
            {counts
              ? ` 구역 건수 — ${SECTIONS.map((key) => `${key} ${countLabel(counts[key])}`).join(" · ")} · 미결정 ${countLabel(undecided)}`
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
