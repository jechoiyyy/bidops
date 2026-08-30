import { useEffect, useMemo, useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router-dom";
import { Badge } from "../components/common/Badge";
import { DataTable, type DataTableColumn } from "../components/common/DataTable";
import { EmptyState } from "../components/common/EmptyState";
import { Panel } from "../components/common/Panel";
import { api } from "../lib/api";
import { formatDateTime, formatNumber } from "../lib/format";
import { originOf, trackingVariant } from "../lib/opportunity";
import type { PreSpecListItem, PreSpecOrigin, PreSpecSort } from "../lib/types";
import "../styles/pre-specs-relaxed.css";

const PAGE_SIZE = 50;
const BUSINESS_DIVISIONS = ["일반용역", "기술용역"] as const;
const ORIGINS: PreSpecOrigin[] = ["추적", "신규"];

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
  if (value === null) return <span className="pre-specs-muted">—</span>;
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
      <span>
        차단 {document["차단"]} · 실패 {document["실패"]}
      </span>
    </div>
  );
}

const columns: DataTableColumn<PreSpecListItem>[] = [
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
        <Link className="pre-specs-title-link" to={`/judgments/${item.notice_pk}`}>
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
    render: (item) => formatDateTime(item.deadline_at),
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
    key: "document",
    header: "문서",
    className: "pre-specs-document-cell",
    render: (item) => documentCell(item),
  },
];

export function PreSpecsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const swOnly = searchParams.get("sw_only") !== "false";
  const businessDivision = validDivision(searchParams.get("business_division"));
  const origin = validOrigin(searchParams.get("origin"));
  const queryText = searchParams.get("q") ?? "";
  const sort = validSort(searchParams.get("sort"));
  const offset = readOffset(searchParams.get("offset"));
  const [searchText, setSearchText] = useState(queryText);

  useEffect(() => setSearchText(queryText), [queryText]);

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
    staleTime: 10_000,
  });
  const items = result.data?.items ?? [];
  const total = result.data?.total ?? 0;
  const hasFilters = swOnly || Boolean(businessDivision || origin || queryText);

  function updateSearchParams(changes: Record<string, string | null>) {
    const next = new URLSearchParams(searchParams);
    for (const [key, value] of Object.entries(changes)) {
      if (value === null || value === "") next.delete(key);
      else next.set(key, value);
    }
    next.delete("offset");
    setSearchParams(next, { replace: true });
  }

  function clearFilters() {
    updateSearchParams({ sw_only: null, business_division: null, origin: null, q: null, sort: null });
    setSearchText("");
  }

  function emptyDescription(): string {
    if (swOnly) return "SW사업대상 기본 필터가 적용되어 있습니다. 필터를 끄거나 업무구분·검색어 조건을 조정해 보십시오.";
    if (businessDivision || origin || queryText) return "현재 선택한 업무구분·구분·검색어 조건에 맞는 누적 데이터가 없습니다.";
    return "누적 수집된 사전규격 데이터가 아직 없습니다.";
  }

  return (
    <section className="pre-specs-page" aria-labelledby="page-title">
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
            <span>SW사업대상만</span>
          </label>
          <span className="pre-specs-filter-help">기본 켜짐 · 끄면 전체 사전규격</span>
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
          description={result.error instanceof Error ? result.error.message : "사전규격 API 응답을 확인할 수 없습니다."}
          action={{ label: "다시 시도", onClick: () => { void result.refetch(); } }}
        />
      ) : null}

      {result.isSuccess ? (
        <Panel
          className="pre-specs-table-panel"
          title="누적 사전규격 목록"
          action={total > 0 ? <span className="panel-meta">{total}건 · {offset + 1}–{Math.min(offset + items.length, total)}</span> : undefined}
        >
          {items.length === 0 ? (
            <EmptyState
              compact
              title="조건에 맞는 사전규격이 없습니다."
              description={emptyDescription()}
              action={hasFilters ? { label: "필터 초기화", onClick: clearFilters } : undefined}
            />
          ) : (
            <DataTable
              className="pre-specs-table"
              columns={columns}
              rows={items}
              rowKey="notice_pk"
            />
          )}
        </Panel>
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
