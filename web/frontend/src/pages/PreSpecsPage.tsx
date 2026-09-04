import { useEffect, useMemo, useState, type ReactNode } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { Badge } from "../components/common/Badge";
import { DataTable, type DataTableColumn } from "../components/common/DataTable";
import { DisabledReason } from "../components/common/DisabledReason";
import { EmptyState } from "../components/common/EmptyState";
import { Panel } from "../components/common/Panel";
import { ReviewStateGroup, SplitWorkspace } from "../components/common/ReviewPrimitives";
import { isInheritedTracking, TrackingDecisionControl, updateTrackingProjection } from "../components/pre-specs/TrackingDecisionControl";
import { api } from "../lib/api";
import { describeDeadline } from "../lib/deadline";
import { formatDateTime, formatNumber } from "../lib/format";
import { originOf, trackingVariant } from "../lib/opportunity";
import {
  PRE_SPEC_OVERVIEW_NOT_STARTED_LABEL,
  PRE_SPEC_OVERVIEW_STATUS_LABEL,
  preSpecOverviewStatusVariant,
} from "../lib/preSpecOverviewStatus";
import type { PreSpecListItem, PreSpecListResponse, PreSpecOrigin, PreSpecOverviewReviewStatus, PreSpecSort } from "../lib/types";
import "../styles/pre-specs-relaxed.css";

// docs/design/PLAN.md 3단계: 목록을 개요 검토 상태별 접이식 그룹으로 바꾼다.
// 페이지 크기를 200으로 올려 (서버 한도 500 이내) 한 페이지 안에서 그룹이
// 실제로 채워지는 경우를 늘린다. 그래도 총 건수가 페이지 크기를 넘으면
// 그룹 헤더의 건수(overview_status_counts, 필터 전체 기준)와 그 그룹 안에
// 실제로 보이는 행 수가 달라질 수 있어, 그 경우를 각주로 명시한다 — 조용히
// 숨기지 않는다(CLAUDE.md unknown/null 보존 게이트와 같은 원칙).
const PAGE_SIZE = 200;
const BUSINESS_DIVISIONS = ["일반용역", "기술용역"] as const;
const ORIGINS: PreSpecOrigin[] = ["추적", "신규"];

// 그룹 표시 순서. 사람 검토 필요·실패를 맨 앞에 두고, 개요 검토 미시작(행
// 없음)을 그 다음에 두어 "아직 시작하지 않음 → 진행 중 → 종료"의 자연스러운
// 순서를 만든다. 완료·취소는 맨 뒤에 둔다.
const GROUP_ORDER: (PreSpecOverviewReviewStatus | null)[] = [
  "needs_human_review",
  "failed",
  null,
  "awaiting_document",
  "awaiting_structure",
  "preparing",
  "awaiting_model",
  "queued",
  "running",
  "completed",
  "cancelled",
];

// 사람 검토 필요·실패는 기본 펼침, 완료는 기본 접힘 — PLAN.md 3단계 원문
// 그대로다. 나머지(미시작 포함 8개 상태)는 실행 중이거나 아직 조치할 일이
// 없는 상태이므로 기본 접힘으로 둔다. 이 결정으로 10값 + null 11개 그룹
// 전부가 화면에 존재하되(0건이어도 표시), 기본 화면은 조치가 필요한
// 항목에 집중된다.
const DEFAULT_EXPANDED_GROUPS: (PreSpecOverviewReviewStatus | null)[] = ["needs_human_review", "failed"];

function groupLabel(status: PreSpecOverviewReviewStatus | null): string {
  return status === null ? PRE_SPEC_OVERVIEW_NOT_STARTED_LABEL : PRE_SPEC_OVERVIEW_STATUS_LABEL[status];
}

function groupBadgeVariant(status: PreSpecOverviewReviewStatus | null) {
  return status === null ? "neutral" : preSpecOverviewStatusVariant(status);
}

function groupStatusDotVariant(status: PreSpecOverviewReviewStatus | null): "success" | "warning" | "error" | "accent" | "neutral" {
  if (status === "completed") return "success";
  if (status === "failed") return "error";
  if (status === "needs_human_review") return "warning";
  if (status === "running" || status === "queued") return "accent";
  return "neutral";
}

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

function formatBudget(value: number | null): string {
  return value === null || Number.isNaN(value) ? "예산 미확인" : `${formatNumber(value)}원`;
}

function swStatusCell(value: string | null): ReactNode {
  if (value === null) return <Badge label="미확인" variant="evidence-unknown" />;
  return <Badge label={value} variant={value === "Y" ? "evidence-confirmed" : "neutral"} />;
}

function originCell(value: PreSpecOrigin | null): ReactNode {
  if (value === null) return <Badge label="구분 미확인" variant="evidence-unknown" />;
  const origin = originOf(value);
  return <Badge label={origin} variant={origin === "추적" ? "grade-1" : "focus"} />;
}

function trackingCell(item: PreSpecListItem): ReactNode {
  if (item.opportunity_id === null) return <span className="pre-specs-muted">—</span>;
  if (item.tracking_status === null) return <Badge label="미확인" variant="neutral" />;
  return <Badge label={item.tracking_status} variant={trackingVariant(item.tracking_status)} />;
}

function documentCell(item: PreSpecListItem): ReactNode {
  const document = item.document;
  return (
    <div className="pre-specs-document-summary" title="첨부 취득 상태 집계">
      <strong>{document.attachments}건</strong>
      <span>
        완료 {document["완료"]} · 대기 {document["대기"]} · 진행 {document["진행"]}
      </span>
      <span className="pre-specs-document-alerts">
        <Badge label={`차단 ${document["차단"]}`} variant={document["차단"] > 0 ? "alert" : "neutral"} />
        <Badge label={`실패 ${document["실패"]}`} variant={document["실패"] > 0 ? "alert" : "neutral"} />
      </span>
    </div>
  );
}

function deadlineCell(value: string | null): ReactNode {
  const deadline = describeDeadline(value);
  return (
    <div className="pre-specs-deadline-stack">
      <span>{formatDateTime(value)}</span>
      <span aria-label={`D-day: ${deadline.label}`} className={`pre-specs-deadline is-${deadline.urgency} mono tabular-nums`}>
        {deadline.label}
      </span>
    </div>
  );
}

/** 목록 화면에서 심층 추적 승인을 내리는 동선(PLAN.md 3단계 3). 사업기회가
 * 없으면 조용히 숨기지 않고 비활성 사유를 aria-describedby로 노출한다. */
function trackingActionCell(item: PreSpecListItem, selectedPk: number | null, onSelect: (pk: number) => void): ReactNode {
  if (item.opportunity_id === null) {
    const reasonId = `pre-specs-tracking-disabled-${item.notice_pk}`;
    return (
      <div className="pre-specs-tracking-action">
        <button type="button" className="pre-specs-tracking-action-button" disabled aria-describedby={reasonId}>
          추적 결정
        </button>
        <DisabledReason id={reasonId}>아직 사업기회에 연결되지 않아 추적 결정을 기록할 수 없습니다.</DisabledReason>
      </div>
    );
  }
  const isSelected = selectedPk === item.notice_pk;
  return (
    <button
      type="button"
      className="pre-specs-tracking-action-button"
      aria-pressed={isSelected}
      aria-expanded={isSelected}
      aria-controls={isSelected ? "pre-specs-tracking-target" : undefined}
      onClick={() => onSelect(item.notice_pk)}
    >
      {isSelected ? "선택됨 · 결정 패널 열림" : "추적 결정"}
    </button>
  );
}

function columns(
  listSearch: string,
  selectedPk: number | null,
  onSelectTracking: (pk: number) => void,
): DataTableColumn<PreSpecListItem>[] {
  return [
  {
    key: "origin",
    header: "구분",
    className: "pre-specs-origin-cell",
    render: (item) => (
      <div className="pre-specs-origin-stack">
        {originCell(item.origin)}
        {item.kept_by_tracking ? (
          <span
            className="pre-specs-tracking-exception"
            title="SW사업대상=Y가 아니지만 추적 중인 발주계획에 연결됨"
          >
            추적 예외
          </span>
        ) : null}
      </div>
    ),
  },
  {
    key: "title",
    header: "사업명·기관",
    className: "pre-specs-title-cell",
    render: (item) => (
      <div className="pre-specs-title-stack">
        <Link
          className="pre-specs-title-link"
          to={{ pathname: `/pre-specs/${item.notice_pk}`, search: listSearch }}
        >
          {item.title?.trim() || "사업명 미확인"}
        </Link>
        <span>{item.agency?.trim() || "발주기관 미확인"}</span>
        {item.pre_spec_no ? <code>{String(item.pre_spec_no)}</code> : <span>사전규격번호 미확인</span>}
      </div>
    ),
  },
  {
    key: "business_division",
    header: "업무구분",
    render: (item) => item.business_division ?? <span className="pre-specs-muted">미확인</span>,
  },
  {
    key: "sw_business_status",
    header: "SW사업대상",
    render: (item) => swStatusCell(item.sw_business_status),
  },
  {
    key: "published_at",
    header: "게시",
    className: "pre-specs-date-cell",
    render: (item) => formatDateTime(item.published_at),
  },
  {
    key: "deadline_at",
    header: "의견등록 마감",
    className: "pre-specs-date-cell",
    render: (item) => deadlineCell(item.deadline_at),
  },
  {
    key: "budget",
    header: "예산",
    className: "pre-specs-budget-cell",
    render: (item) => formatBudget(item.budget),
  },
  {
    key: "tracking_status",
    header: "추적 상태",
    render: (item) => trackingCell(item),
  },
  {
    key: "tracking_action",
    header: "심층 추적 승인",
    className: "pre-specs-tracking-action-cell",
    render: (item) => trackingActionCell(item, selectedPk, onSelectTracking),
  },
  {
    key: "document",
    header: "문서",
    className: "pre-specs-document-cell",
    render: (item) => documentCell(item),
  },
  ];
}

export function PreSpecsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const swOnly = searchParams.get("sw_only") !== "false";
  const businessDivision = validDivision(searchParams.get("business_division"));
  const origin = validOrigin(searchParams.get("origin"));
  const queryText = searchParams.get("q") ?? "";
  const sort = validSort(searchParams.get("sort"));
  const offset = readOffset(searchParams.get("offset"));
  const [searchText, setSearchText] = useState(queryText);
  const [selectedTrackingPk, setSelectedTrackingPk] = useState<number | null>(null);

  useEffect(() => setSearchText(queryText), [queryText]);
  useEffect(() => {
    setSelectedTrackingPk(null);
  }, [businessDivision, offset, origin, queryText, sort, swOnly]);

  const listQuery = useMemo(
    () => ({
      sw_only: swOnly,
      business_division: businessDivision || null,
      origin: origin || null,
      q: queryText || null,
      sort,
      limit: PAGE_SIZE,
      offset,
    }),
    [businessDivision, offset, origin, queryText, sort, swOnly],
  );
  const result = useQuery({
    queryKey: ["pre-specs", listQuery],
    queryFn: ({ signal }) => api.getPreSpecs(listQuery, { signal }),
    // 기본값으로 돌아왔을 때도 sw_only=true 요청을 다시 보내 ADR-0031의
    // 서버 기본 projection과 화면 상태가 같은지 확인한다.
    staleTime: 0,
  });
  const items = result.data?.items ?? [];
  const total = result.data?.total ?? 0;
  const overviewStatusCounts = result.data?.overview_status_counts ?? [];
  const isDefaultView = swOnly && !businessDivision && !origin && !queryText && sort === "published" && offset === 0;
  const tableColumns = useMemo(
    () => columns(searchParams.toString(), selectedTrackingPk, (pk) => setSelectedTrackingPk((current) => (current === pk ? null : pk))),
    [searchParams, selectedTrackingPk],
  );

  const countByStatus = useMemo(() => {
    const map = new Map<PreSpecOverviewReviewStatus | null, number>();
    for (const row of overviewStatusCounts) map.set(row.status, row.count);
    return map;
  }, [overviewStatusCounts]);
  const itemsByStatus = useMemo(() => {
    const map = new Map<PreSpecOverviewReviewStatus | null, PreSpecListItem[]>();
    for (const item of items) {
      const key = item.overview_review_status;
      const bucket = map.get(key);
      if (bucket) bucket.push(item);
      else map.set(key, [item]);
    }
    return map;
  }, [items]);
  const selectedTrackingItem = items.find((item) => item.notice_pk === selectedTrackingPk);

  function updateSearchParams(changes: Record<string, string | null>) {
    const next = new URLSearchParams(searchParams);
    for (const [key, value] of Object.entries(changes)) {
      if (value === null || value === "") next.delete(key);
      else next.set(key, value);
    }
    next.delete("offset");
    setSearchParams(next, { replace: true });
  }

  function restoreDefaults() {
    updateSearchParams({ sw_only: null, business_division: null, origin: null, q: null, sort: null });
    setSearchText("");
  }

  function showAllPreSpecs() {
    updateSearchParams({ sw_only: "false" });
  }

  function emptyDescription(): string {
    if (isDefaultView) return "SW 중심 기본 보기에 맞는 항목이 없습니다. 전체 보기는 SW사업대상과 무관한 사전규격까지 명시적으로 요청합니다.";
    if (swOnly) return "SW 중심 기본 보기와 추가 필터가 함께 적용되어 있습니다. 기본값으로 돌아가거나 조건을 조정해 보십시오.";
    if (businessDivision || origin || queryText) return "현재 선택한 업무구분·구분·검색어 조건에 맞는 누적 데이터가 없습니다.";
    return "누적 수집된 사전규격 데이터가 아직 없습니다.";
  }

  return (
    <section className="pre-specs-page" data-astryx-theme="bidops" aria-labelledby="page-title">
      <header className="pre-specs-page-header">
        <div>
          <span className="pre-specs-eyebrow">모니터링 · 누적 조회</span>
          <h2 id="page-title">사전규격</h2>
          <p>
            회차가 아닌 누적 사전규격을 확인합니다. SW사업대상은 화면 필터이며, 추적 중인 발주계획 연결은 라벨과 관계없이 보존됩니다.
          </p>
        </div>
        <div className="pre-specs-count" aria-live="polite">
          <strong className="mono">{total}</strong>
          <span>건</span>
        </div>
      </header>

      <section className="pre-specs-filter-panel" aria-label="사전규격 필터">
        <div className="pre-specs-filter-row">
          <label className="pre-specs-switch">
            <input
              checked={swOnly}
              type="checkbox"
              onChange={(event) => updateSearchParams({ sw_only: event.target.checked ? null : "false" })}
            />
            <span>SW 중심 · 추적 예외 포함</span>
          </label>
          <span className="pre-specs-filter-help">기본 보기 · 해제 시 전체 사전규격을 명시적으로 요청</span>
          <label>
            <span>업무구분</span>
            <select
              value={businessDivision}
              onChange={(event) => updateSearchParams({ business_division: event.target.value || null })}
            >
              <option value="">전체</option>
              {BUSINESS_DIVISIONS.map((value) => <option key={value} value={value}>{value}</option>)}
            </select>
          </label>
          <label>
            <span>구분</span>
            <select value={origin} onChange={(event) => updateSearchParams({ origin: event.target.value || null })}>
              <option value="">전체</option>
              {ORIGINS.map((value) => <option key={value} value={value}>{value}</option>)}
            </select>
          </label>
          <label>
            <span>정렬</span>
            <select value={sort} onChange={(event) => updateSearchParams({ sort: event.target.value || null })}>
              <option value="published">게시 최신순</option>
              <option value="deadline">마감 임박순</option>
            </select>
          </label>
          <form
            className="pre-specs-search"
            onSubmit={(event) => {
              event.preventDefault();
              updateSearchParams({ q: searchText.trim() || null });
            }}
          >
            <label htmlFor="pre-spec-search">사업명·기관명 검색</label>
            <div>
              <input
                id="pre-spec-search"
                value={searchText}
                placeholder="부분일치"
                onChange={(event) => setSearchText(event.target.value)}
              />
              <button type="submit">검색</button>
            </div>
          </form>
          <button className="pre-specs-reset" type="button" onClick={restoreDefaults}>기본값으로</button>
        </div>
        <p className="pre-specs-policy-note">
          추적 예외는 <strong>SW사업대상=Y가 아니지만 추적 중인 발주계획에 연결됨</strong>을 뜻합니다. 값이 없는 SW사업대상은 미확인으로 표시합니다.
        </p>
      </section>

      {result.isPending ? <div className="pre-specs-loading" role="status" aria-live="polite">사전규격 목록을 불러오는 중입니다.</div> : null}
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
            <Panel
              className="pre-specs-table-panel"
              title="누적 사전규격 목록 · 개요 검토 상태별"
              action={total > 0 ? <span className="panel-meta">{total}건 · {offset + 1}–{Math.min(offset + items.length, total)}</span> : undefined}
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
                <div className="pre-specs-groups" role="list" aria-label="개요 검토 상태 그룹">
                  {GROUP_ORDER.map((status) => {
                    const count = countByStatus.get(status) ?? 0;
                    const groupItems = itemsByStatus.get(status) ?? [];
                    const groupKeyText = status ?? "null";
                    const isPartial = count > 0 && groupItems.length !== count;
                    return (
                      <div className="pre-specs-group" role="listitem" key={groupKeyText}>
                        <ReviewStateGroup
                          count={count}
                          defaultIsOpen={DEFAULT_EXPANDED_GROUPS.includes(status)}
                          label={
                            <span className="pre-specs-group-trigger">
                              <Badge label={groupLabel(status)} variant={groupBadgeVariant(status)} />
                            </span>
                          }
                          status={{ label: groupLabel(status), variant: groupStatusDotVariant(status) }}
                          value={groupKeyText}
                        >
                          {count === 0 ? (
                            <p className="pre-specs-group-empty">이 상태의 사전규격이 현재 필터에 없습니다.</p>
                          ) : (
                            <>
                              {isPartial ? (
                                <p className="pre-specs-group-partial">
                                  전체 {count}건 중 현재 페이지에 표시된 {groupItems.length}건만 보입니다. 페이지를 이동하거나 검색 조건을 좁혀 나머지를 확인하십시오.
                                </p>
                              ) : null}
                              {groupItems.length === 0 ? (
                                <p className="pre-specs-group-empty">
                                  전체 {count}건이 있지만 현재 불러온 페이지에는 없습니다. 페이지를 이동하거나 검색 조건을 좁혀 보십시오.
                                </p>
                              ) : (
                                <DataTable
                                  className="pre-specs-table"
                                  columns={tableColumns}
                                  onRowSelect={(item) => setSelectedTrackingPk(item.notice_pk)}
                                  rows={groupItems}
                                  rowKey="notice_pk"
                                  selectedRowKey={selectedTrackingPk}
                                />
                              )}
                            </>
                          )}
                        </ReviewStateGroup>
                      </div>
                    );
                  })}
                </div>
              )}
            </Panel>
          </section>

          <section className="review-split-detail pre-specs-detail-pane" aria-label="선택한 사전규격 상세">
            {selectedTrackingItem ? (
              <div id="pre-specs-tracking-target">
                <Panel
                  className="pre-specs-tracking-target-panel"
                  title={`심층 추적 승인 · ${selectedTrackingItem.title?.trim() || "사업명 미확인"}`}
                  action={(
                    <span className="pre-specs-detail-actions">
                      {/* 이 화면의 결정은 심층 검토 실행 승인이다(PLAN 단계 D 작업 3).
                          문서 묶음 준비와 승인은 상세가 소유하므로 그 자리로 보낸다. */}
                      <Link to={`/pre-specs/${selectedTrackingItem.notice_pk}${searchParams.toString() ? `?${searchParams.toString()}` : ""}`}>
                        심층 검토 실행 →
                      </Link>
                      <button type="button" onClick={() => setSelectedTrackingPk(null)}>닫기</button>
                    </span>
                  )}
                >
                  {/* 신규 사전규격에만 `추적 시작하고 심층 검토`를 한 조작으로 준다
                      (ADR-0045 결정 6, PLAN 단계 D 작업 4). 승계된 건은 컨트롤이
                      추적 상태를 다시 묻지 않으므로 이 prop이 쓰이지 않는다. */}
                  <TrackingDecisionControl
                    item={selectedTrackingItem}
                    isPending={result.isPending}
                    isError={result.isError}
                    onRetry={() => { void result.refetch(); }}
                    headingLevel="h4"
                    onStartedForDeepReview={isInheritedTracking(selectedTrackingItem)
                      ? undefined
                      : () => navigate(`/pre-specs/${selectedTrackingItem.notice_pk}${searchParams.toString() ? `?${searchParams.toString()}` : ""}`)}
                    onSaved={(saved) => {
                      const noticePk = selectedTrackingItem.notice_pk;
                      queryClient.setQueryData<PreSpecListResponse>(
                        ["pre-spec-detail", noticePk],
                        (current) => updateTrackingProjection(current, noticePk, saved),
                      );
                      queryClient.setQueriesData<PreSpecListResponse>(
                        { queryKey: ["pre-specs"] },
                        (current) => updateTrackingProjection(current, noticePk, saved),
                      );
                      void queryClient.invalidateQueries({ queryKey: ["pre-spec-overview-reviews-v2", noticePk] });
                      void queryClient.invalidateQueries({ queryKey: ["pre-spec-detail", noticePk] });
                      void queryClient.invalidateQueries({ queryKey: ["pre-specs"] });
                      void queryClient.invalidateQueries({ queryKey: ["opportunity", saved.id] });
                    }}
                  />
                </Panel>
              </div>
            ) : (
              <Panel className="pre-specs-selection-empty-panel" title="선택한 사전규격">
                <EmptyState
                  compact
                  title="사전규격을 선택하십시오."
                  description="왼쪽 목록에서 행을 선택하면 추적 상태와 승인 사유를 기록할 수 있습니다. 이 선택은 최종 Go/No-Go와 별개입니다."
                />
              </Panel>
            )}
          </section>
        </SplitWorkspace>
      ) : null}

      {result.isSuccess && total > PAGE_SIZE ? (
        <nav className="pre-specs-pager" aria-label="사전규격 목록 페이지">
          <button
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
          <span>{offset + 1}–{Math.min(offset + items.length, total)} / {total}</span>
          <button
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
    </section>
  );
}
