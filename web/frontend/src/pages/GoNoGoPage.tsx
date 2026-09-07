import { useState } from "react";
import { useQueries, useQuery } from "@tanstack/react-query";
import { useNavigate, useSearchParams } from "react-router-dom";
import { Button } from "@astryxdesign/core/Button";
import { Dialog, DialogHeader } from "@astryxdesign/core/Dialog";
import { Heading } from "@astryxdesign/core/Heading";
import { Selector } from "@astryxdesign/core/Selector";
import { Table, pixel, proportional } from "@astryxdesign/core/Table";
import { Text } from "@astryxdesign/core/Text";
import { TextInput } from "@astryxdesign/core/TextInput";
import { Token } from "@astryxdesign/core/Token";
import {
  Activity,
  ArrowRight,
  Building2,
  Check,
  ChevronRight,
  Clock,
  RefreshCw,
  Search,
} from "lucide-react";
import { EmptyState } from "../components/common/EmptyState";
import { SkeletonPanel } from "../components/common/Skeleton";
import { getBidDelta, getBidDeltaComparison } from "../components/bid-delta/api";
import {
  CATEGORY_LABELS,
  countDeltaItems,
  decisionRelevantItems,
  defaultComparison,
  itemKindLabel,
  evidenceLocationLabel,
  SHORT_CALCULATION_LABELS,
  formatMoment,
  shortHash,
} from "../components/bid-delta/labels";
import type {
  BidDeltaComparisonSummary,
  BidDeltaComparisonView,
  BidDeltaEvidenceView,
  BidDeltaItemView,
  BidDeltaWorkspaceView,
} from "../components/bid-delta/types";
import { api } from "../lib/api";
import { apiErrorRecoveryAction, describeApiError } from "../lib/apiErrors";
import type { OpportunityListItem } from "../lib/types";
import "../styles/go-no-go.css";

// docs/design/PLAN.md 2단계 · ADR-0041 결정 3: 최종 Go/No-Go를 최상위 메뉴로
// 올린다. 빈도는 낮아도 되돌릴 수 없는 결정이며, 지금까지 사이드바에서 도달할
// 길이 없이 /opportunities/:id/bid-delta 안에만 있었다.
//
// 승인된 시안(`design-previews/bidops-go-no-go-erp-20260907/`)의 구조를 그대로
// 옮긴다: 목록 38% / 상세 62%, 사업명·발주기관 15px, 보조정보 14px, 상세는
// 검토 요약 / 비교 문서 / 결정 기록 세 탭, 바닥에 현재 사람 결정과 결정 화면을
// 여는 액션 하나.
//
// 이 화면은 결정 화면이 아니라 **결정 검토 목록**이다. 실제 Go/No-Go 저장은 계속
// BidDeltaDecisionPage에서만 한다(시안도 목록에서 저장하지 않는다). 적합성 등급·
// 참여 준비 상태·심층 추적 승인을 이 화면에서 대신 채우지 않는다(ADR-0041 결정 5).
//
// 서버에 결정 목록·집계 endpoint가 없다(routers/bid_delta.py는 사업기회 하나의
// workspace만 준다). 추적 중인 사업기회를 페이지 단위로 받고 **화면에 있는 행만**
// 결정 상태를 조회한다. 조회 전 상태를 "결정 없음"으로 단정하지 않는다.

/** 시안의 네 보기. `review`가 기본이고 URL의 `show`와 동기화한다. */
type DecisionView = "review" | "recheck" | "decided" | "all";

const VIEWS: Array<{ key: DecisionView; label: string }> = [
  { key: "review", label: "검토 대상" },
  { key: "recheck", label: "재검토" },
  { key: "decided", label: "결정 기록" },
  { key: "all", label: "전체" },
];

type DetailTab = "summary" | "documents" | "decision";

const DETAIL_TABS: Array<{ key: DetailTab; label: string }> = [
  { key: "summary", label: "검토 요약" },
  { key: "documents", label: "비교 문서" },
  { key: "decision", label: "결정 기록" },
];

// 한 화면이 사업기회 100건을 받고 **행마다** workspace를 하나씩 조회했다 —
// 최대 101 요청이다. 서버에 결정 목록 엔드포인트가 없다는 사실은 그대로지만,
// 한 번에 보는 만큼만 받으면 행 조회도 그만큼으로 줄어든다.
const PAGE_SIZE = 25;

function readOffset(raw: string | null): number {
  const parsed = Number(raw);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : 0;
}

function readView(raw: string | null): DecisionView {
  return VIEWS.some((view) => view.key === raw) ? (raw as DecisionView) : "review";
}

/** 사람이 아는 이름으로 행을 연다. 식별자만 있는 행은 담당자가 무슨 사업인지
 * 알 수 없어 결국 하나씩 열어 봐야 한다(`GoNoGo` 아트보드). */
function opportunityTitle(item: OpportunityListItem): string {
  const named = item.links.find((link) => link.title && link.title.trim());
  return named?.title?.trim() ?? "제목 미확인";
}

function opportunityAgency(item: OpportunityListItem): string {
  return item.links.find((link) => link.agency && link.agency.trim())?.agency?.trim() ?? "발주기관 미확인";
}

interface DecisionRow extends Record<string, unknown> {
  opportunity: OpportunityListItem;
  workspace: BidDeltaWorkspaceView | undefined;
  isPending: boolean;
  isError: boolean;
  id: number;
  /** 이 행의 결정 상태(workspace) 조회만 다시 부른다. */
  refetchWorkspace: () => void;
}

/** 조회가 끝났고 workspace를 받은 행만 결정 상태를 말할 수 있다. */
function isLoaded(row: DecisionRow): boolean {
  return !row.isPending && !row.isError && Boolean(row.workspace);
}

/**
 * 기본 검토 대상.
 *
 * 미결정만 남기면 **오래된 Go 결정**이 목록에서 사라진다. 새 정정공고로 현재성이
 * `stale`이 된 결정과 현재성 `unknown`은 담당자가 다시 봐야 하는 것이지 끝난 것이
 * 아니다. 조회 중·조회 실패도 어느 쪽으로도 단정하지 않고 남긴다.
 */
function isReviewTarget(row: DecisionRow): boolean {
  if (!isLoaded(row)) return true;
  const workspace = row.workspace as BidDeltaWorkspaceView;
  if (!workspace.latest_final_decision) return true;
  return workspace.decision_currentness !== "current";
}

function isRecheckTarget(row: DecisionRow): boolean {
  if (!isLoaded(row)) return false;
  const workspace = row.workspace as BidDeltaWorkspaceView;
  return Boolean(workspace.latest_final_decision) && workspace.decision_currentness !== "current";
}

function hasDecisionRecord(row: DecisionRow): boolean {
  return isLoaded(row) && Boolean((row.workspace as BidDeltaWorkspaceView).latest_final_decision);
}

function matchesView(row: DecisionRow, view: DecisionView): boolean {
  if (view === "all") return true;
  if (view === "review") return isReviewTarget(row);
  if (view === "recheck") return isRecheckTarget(row);
  return hasDecisionRecord(row);
}

/** 사람 결정 한 줄. 조회 전·실패를 미결정으로 바꾸지 않는다. */
function decisionStateLabel(row: DecisionRow): string {
  if (row.isPending) return "조회 중";
  if (row.isError) return "조회 실패";
  const workspace = row.workspace;
  if (!workspace) return "결정 상태 unknown";
  const decision = workspace.latest_final_decision;
  if (!decision) return "미결정";
  const value = decision.decision === "go" ? "Go" : "No-Go";
  if (workspace.decision_currentness === "stale") return `${value} · 재검토`;
  if (workspace.decision_currentness === "unknown") return `${value} · 효력 미확인`;
  return value;
}

function decisionSubLabel(row: DecisionRow): string | null {
  if (!isLoaded(row)) return null;
  const workspace = row.workspace as BidDeltaWorkspaceView;
  // 결정이 없으면 현재성은 말할 것이 없다. 기록 없음에 `현재성 미확인`을 덧붙이면
  // 없는 결정이 확인 대기 중인 것처럼 읽힌다.
  if (!workspace.latest_final_decision) return "기록 없음";
  if (workspace.decision_currentness === "stale") return "재계산·재검토 필요";
  if (workspace.decision_currentness === "unknown") return "현재성 미확인";
  return "기록 있음";
}

/** 비교 계산 상태 한 낱말. 비교가 0건인 것은 값이고 조회 전은 미확인이다. */
function comparisonStateLabel(row: DecisionRow): string {
  if (!isLoaded(row)) return "비교 상태 미확인";
  const active = defaultComparison((row.workspace as BidDeltaWorkspaceView).comparisons);
  // 비교 0건을 `비교 0건`으로 눌러 담으면 "아직 안 봤다"와 "봤는데 비교할 것이
  // 없다"가 같은 자리에서 사라진다(PLAN 단계 E 작업 5).
  if (!active) return "변경 비교 결과 없음";
  return SHORT_CALCULATION_LABELS[active.calculation_status];
}

function EvidenceSide({
  side,
  evidence,
}: {
  side: "baseline" | "comparison";
  evidence: BidDeltaEvidenceView | null;
}) {
  return (
    <div>
      <Text className="gng-caption" type="supporting" color="secondary" as="p">
        {side === "baseline" ? "기준 사전규격" : "대상 입찰공고"}
        {evidence ? ` · ${evidenceLocationLabel(evidence)}` : ""}
      </Text>
      <Text as="p">{evidence?.quote ?? "원문 근거 미확인"}</Text>
      {evidence ? (
        <Text className="gng-caption" type="supporting" color="secondary" as="p">
          근거 검증 {evidence.verification_status === "verified"
            ? "verified · 검증됨"
            : evidence.verification_status === "missing" ? "missing · 근거 없음" : "mismatch · 불일치"}
          {" · 문서 원문 해시 "}{shortHash(evidence.source_sha256)}
        </Text>
      ) : null}
    </div>
  );
}

export function GoNoGoPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();
  const view = readView(searchParams.get("show"));
  const offset = readOffset(searchParams.get("offset"));
  const query = searchParams.get("q") ?? "";
  const selectedParam = Number(searchParams.get("selected"));
  const [tab, setTab] = useState<DetailTab>("summary");
  const [dialog, setDialog] = useState<"data" | "evidence" | null>(null);
  const [evidenceItem, setEvidenceItem] = useState<BidDeltaItemView | null>(null);

  // 최종 Go/No-Go까지 가는 것은 계속 추적하기로 한 사업기회다. 보류·종료·미선택을
  // 결정 검토 대상으로 끌어올리지 않는다.
  const opportunitiesQuery = useQuery({
    queryKey: ["opportunities", "tracking", "계속 추적", offset],
    queryFn: ({ signal }) => api.getOpportunities(
      { tracking_status: "계속 추적", limit: PAGE_SIZE, offset },
      { signal },
    ),
    staleTime: 30_000,
  });
  const opportunities = opportunitiesQuery.data?.items ?? [];
  const total = opportunitiesQuery.data?.total ?? opportunities.length;
  const returnSearch = searchParams.toString();

  const workspaceQueries = useQueries({
    queries: opportunities.map((item) => ({
      queryKey: ["bid-delta", item.id],
      queryFn: () => getBidDelta(item.id),
      staleTime: 30_000,
    })),
  });

  const rows: DecisionRow[] = opportunities.map((opportunity, index) => ({
    id: opportunity.id,
    opportunity,
    workspace: workspaceQueries[index]?.data,
    isPending: workspaceQueries[index]?.isPending ?? true,
    isError: workspaceQueries[index]?.isError ?? false,
    // 실패한 것은 이 행의 결정 상태 조회다. 사업기회 목록을 다시 받아도 실패한
    // workspace 조회는 그대로 실패로 남는다 — 실패한 그 조회를 다시 부른다.
    refetchWorkspace: () => { void workspaceQueries[index]?.refetch(); },
  }));

  // 검색은 서버 인자가 없어 **받은 페이지 안에서만** 좁히는 브라우저 쪽 필터다.
  // 그 사실은 필터 줄이 직접 말한다(web/frontend/AGENTS.md 검토 흐름).
  const trimmedQuery = query.trim();
  const scope = trimmedQuery
    ? rows.filter((row) => `${opportunityTitle(row.opportunity)} ${opportunityAgency(row.opportunity)}`.includes(trimmedQuery))
    : rows;
  const visibleRows = scope.filter((row) => matchesView(row, view));

  const selectedRow = visibleRows.find((row) => row.id === selectedParam) ?? visibleRows[0];
  const selectedWorkspace = selectedRow?.workspace;
  const comparisons: BidDeltaComparisonSummary[] = selectedWorkspace?.comparisons ?? [];
  const comparisonParam = searchParams.get("comparison");
  const activeComparison = comparisons.find((item) => item.id === comparisonParam)
    ?? defaultComparison(comparisons);

  // 선택한 사업기회의 **선택한 비교 하나만** 상세를 받는다. 목록의 모든 행에 대해
  // 상세 보고서를 미리 받지 않는다.
  const comparisonQuery = useQuery<BidDeltaComparisonView>({
    queryKey: ["bid-delta-comparison", selectedRow?.id ?? 0, activeComparison?.id ?? ""],
    queryFn: () => getBidDeltaComparison(selectedRow?.id as number, activeComparison?.id as string),
    enabled: Boolean(selectedRow && activeComparison),
    staleTime: 30_000,
  });
  const comparisonView = activeComparison ? comparisonQuery.data : undefined;
  const counts = comparisonView && comparisonView.calculation_status === "completed"
    ? countDeltaItems(comparisonView.items)
    : null;
  const relevantItems = comparisonView ? decisionRelevantItems(comparisonView.items) : [];
  const latestDecision = selectedWorkspace?.latest_final_decision ?? null;
  const currentness = selectedWorkspace?.decision_currentness ?? "unknown";
  // 저장 전제조건은 결정 화면의 규칙 그대로다(계산 완료 · 결과가 분석 실패가 아님).
  // 여기서 느슨하게 만들지 않고 같은 문장으로만 안내한다.
  const canRecordDecision = Boolean(
    comparisonView
    && comparisonView.calculation_status === "completed"
    && comparisonView.result_status !== "failed",
  );

  function patchParams(patch: Record<string, string | null>) {
    const params = new URLSearchParams(searchParams);
    for (const [key, value] of Object.entries(patch)) {
      if (value === null || value === "") params.delete(key);
      else params.set(key, value);
    }
    setSearchParams(params, { replace: true });
  }

  function setView(next: DecisionView) {
    // 보는 범위가 달라진다. 옛 페이지 위치와 옛 선택을 그대로 두면 빈 페이지가
    // 열리거나 목록에 없는 행의 상세가 남는다.
    patchParams({ show: next === "review" ? null : next, offset: null, selected: null, comparison: null });
    setTab("summary");
  }

  function selectRow(id: number) {
    patchParams({ selected: String(id), comparison: null });
    setTab("summary");
  }

  function resetFilters() {
    patchParams({ show: null, q: null, offset: null, selected: null, comparison: null });
    setTab("summary");
  }

  function goToOffset(next: number) {
    patchParams({ offset: next > 0 ? String(next) : null, selected: null, comparison: null });
  }

  function openReview() {
    if (!selectedRow) return;
    const search = new URLSearchParams();
    if (activeComparison) search.set("comparison", activeComparison.id);
    if (returnSearch) search.set("back", returnSearch);
    navigate({ pathname: `/opportunities/${selectedRow.id}/bid-delta`, search: search.toString() });
  }

  const opportunitiesProblem = opportunitiesQuery.error
    ? describeApiError(opportunitiesQuery.error, "추적 중인 사업기회 목록을 확인할 수 없습니다.")
    : null;

  const columns = [
    {
      key: "business",
      header: "사업명 / 발주기관",
      width: proportional(1),
      renderCell: (row: DecisionRow) => (
        <button
          type="button"
          className="gng-row"
          aria-pressed={selectedRow?.id === row.id}
          onClick={() => selectRow(row.id)}
        >
          <Text className="gng-row-title" as="span">{opportunityTitle(row.opportunity)}</Text>
          <Text className="gng-row-agency" as="span">{opportunityAgency(row.opportunity)}</Text>
          <Text className="gng-caption" type="supporting" color="secondary" as="span">
            {comparisonStateLabel(row)} · 사업기회 {row.id}
          </Text>
        </button>
      ),
    },
    {
      key: "decision",
      header: "사람 결정",
      width: pixel(112),
      renderCell: (row: DecisionRow) => (
        <div className="gng-decision-cell">
          <Text className="gng-decision-state" as="span">{decisionStateLabel(row)}</Text>
          {decisionSubLabel(row) ? (
            <Text className="gng-caption" type="supporting" color="secondary" as="span">{decisionSubLabel(row)}</Text>
          ) : null}
        </div>
      ),
    },
  ];

  const availability = selectedRow && !comparisonView ? (
    <div className="gng-availability">
      <Clock aria-hidden="true" />
      <Heading level={3}>
        {selectedRow.isPending ? "결정 상태를 확인하고 있습니다"
          : selectedRow.isError ? "결정 상태를 불러오지 못했습니다"
            : !activeComparison ? "변경 비교 결과가 아직 없습니다"
              : comparisonQuery.isError ? "비교 상세를 불러오지 못했습니다"
                : "비교 상세를 불러오는 중입니다"}
      </Heading>
      <Text as="p">
        {!isLoaded(selectedRow)
          ? "조회가 끝나기 전에는 미결정 또는 변경 없음으로 표시하지 않습니다."
          : !activeComparison
            ? "비교할 사전규격과 입찰공고 문서를 사람이 고른 뒤 비교를 시작해야 합니다. 비교가 없다는 것은 변경이 없다는 뜻이 아닙니다."
            : comparisonQuery.isError
              ? "조회 실패를 변경 없음으로 해석하지 않습니다."
              : "결과가 나올 때까지 중요 변경과 확인 필요 건수는 미확인으로 남습니다."}
      </Text>
      {selectedRow.isError || comparisonQuery.isError ? (
        <Button
          label="다시 조회"
          size="sm"
          onClick={() => {
            if (selectedRow.isError) selectedRow.refetchWorkspace();
            if (comparisonQuery.isError) void comparisonQuery.refetch();
          }}
        />
      ) : null}
    </div>
  ) : null;

  return (
    <section aria-labelledby="go-no-go-title" className="gng-page" data-astryx-theme="bidops">
      <header className="gng-page-header">
        <Heading level={2} id="go-no-go-title">최종 Go/No-Go</Heading>
        <Button label="데이터 현황" variant="ghost" size="sm" icon={<Activity aria-hidden="true" />} onClick={() => setDialog("data")} />
      </header>

      {opportunitiesQuery.isError ? (
        <EmptyState
          compact
          tone="error"
          title="추적 중인 사업기회를 불러오지 못했습니다."
          description="조회 실패를 결정 대기 없음으로 해석하지 않습니다."
          problem={opportunitiesProblem ?? undefined}
          action={opportunitiesProblem
            ? apiErrorRecoveryAction(opportunitiesProblem, () => { void opportunitiesQuery.refetch(); })
            : undefined}
        />
      ) : null}

      {opportunitiesQuery.isPending ? (
        <SkeletonPanel label="추적 중인 사업기회를 불러오는 중" lines={5} />
      ) : null}

      {!opportunitiesQuery.isPending && !opportunitiesQuery.isError ? (
        <>
          <section className="gng-filters" aria-label="결정 검토 목록 필터">
            <div className="gng-filter-line">
              <div className="gng-view-tabs">
                {VIEWS.map((item) => (
                  <Button
                    key={item.key}
                    label={`${item.label}  ${scope.filter((row) => matchesView(row, item.key)).length}`}
                    size="sm"
                    aria-pressed={view === item.key}
                    onClick={() => setView(item.key)}
                  />
                ))}
              </div>
              <TextInput
                label="사업명·발주기관 검색"
                isLabelHidden
                placeholder="사업명·발주기관 검색"
                value={query}
                onChange={(value) => patchParams({ q: value, selected: null, comparison: null })}
                startIcon={Search}
                hasClear
                size="sm"
              />
            </div>
            <div className="gng-filter-context">
              <Text className="gng-caption" type="supporting" color="secondary" as="p">
                계속 추적 중인 사업 · 미결정·재검토·조회 미확인 포함
                {trimmedQuery ? " · 검색은 받은 페이지 안에서만 좁힙니다" : ""}
              </Text>
              <Text className="gng-caption" type="supporting" color="secondary" as="p">
                받은 {rows.length.toLocaleString("ko-KR")}건 기준
              </Text>
            </div>
          </section>

          <div className="gng-workspace">
            <section className="gng-list-pane" aria-label="최종 결정 검토 목록">
              <header className="gng-list-head">
                <Text className="gng-list-title" as="p">결정 검토 목록 · {visibleRows.length.toLocaleString("ko-KR")}건</Text>
                <Text className="gng-caption" type="supporting" color="secondary" as="p">사람 결정 기준</Text>
              </header>
              <div className="gng-table-scroll">
                {visibleRows.length > 0 ? (
                  <Table
                    data={visibleRows}
                    columns={columns}
                    idKey="id"
                    density="compact"
                    dividers="rows"
                    hasHover
                    verticalAlign="top"
                  />
                ) : (
                  <div className="gng-list-empty">
                    <Search aria-hidden="true" />
                    <Heading level={3}>조건에 맞는 사업이 없습니다</Heading>
                    <Text className="gng-caption" type="supporting" color="secondary" as="p">
                      받은 페이지 안에 없을 뿐, 전체에 없다는 뜻은 아닙니다.
                    </Text>
                    <Button label="필터 초기화" size="sm" onClick={resetFilters} />
                  </div>
                )}
              </div>
              <footer className="gng-list-foot">
                {/* 상단 요약은 받은 목록에서 센 값이다. 서버가 결정 상태를 집계하지
                    않으므로 전체 총계로 읽으면 안 된다(docs/tracking/findings.md). */}
                <p className="gng-summary">
                  받은 {rows.length.toLocaleString("ko-KR")}건 기준 · {visibleRows.length.toLocaleString("ko-KR")}건 표시 ·
                  {" "}전체 총계가 아닙니다
                </p>
                {/* 페이저는 이 페이지의 모든 행이 보기 조건에 걸러졌을 때도 남는다.
                    다음 페이지로 갈 길까지 사라지면 "없다"와 "이 페이지에 없다"가
                    같아진다. */}
                {total > PAGE_SIZE ? (
                  <nav aria-label="사업기회 목록 페이지" className="gng-pager">
                    <button
                      className="interaction-control"
                      type="button"
                      disabled={offset === 0}
                      onClick={() => goToOffset(Math.max(0, offset - PAGE_SIZE))}
                    >
                      이전
                    </button>
                    <Text className="gng-caption" type="supporting" color="secondary" as="span">
                      {offset + 1}–{Math.min(offset + opportunities.length, total)} / {total}
                    </Text>
                    <button
                      className="interaction-control"
                      type="button"
                      disabled={offset + PAGE_SIZE >= total}
                      onClick={() => goToOffset(offset + PAGE_SIZE)}
                    >
                      다음
                    </button>
                  </nav>
                ) : null}
              </footer>
            </section>

            <section className="gng-detail-pane" aria-label="선택한 결정 검토 사업">
              {selectedRow ? (
                <>
                  <header className="gng-detail-head">
                    <div className="gng-agency">
                      <Building2 aria-hidden="true" />
                      <Text className="gng-caption" type="supporting" color="secondary" as="span">발주기관</Text>
                      <Text className="gng-agency-name" as="span">{opportunityAgency(selectedRow.opportunity)}</Text>
                    </div>
                    <Heading level={2}>{opportunityTitle(selectedRow.opportunity)}</Heading>
                    <div className="gng-row-line gng-spread">
                      <Text className="gng-caption" type="supporting" color="secondary" as="p">
                        사업기회 {selectedRow.id} · {selectedRow.opportunity.tracking_status}
                        {selectedRow.opportunity.recheck_signal ? " · 재확인 신호 있음" : ""}
                      </Text>
                      <Token size="sm" label={decisionStateLabel(selectedRow)} />
                    </div>
                  </header>

                  <nav className="gng-detail-tabs" aria-label="선택한 사업 상세 보기">
                    {DETAIL_TABS.map((item) => (
                      <Button
                        key={item.key}
                        label={item.label}
                        size="sm"
                        aria-pressed={tab === item.key}
                        onClick={() => setTab(item.key)}
                      />
                    ))}
                  </nav>

                  <div className="gng-detail-scroll">
                    {tab === "summary" ? (
                      <>
                        {latestDecision && currentness !== "current" ? (
                          <div className="gng-review-notice">
                            <RefreshCw aria-hidden="true" />
                            <div>
                              <Text weight="semibold" as="p">
                                기존 {latestDecision.decision === "go" ? "Go" : "No-Go"} 결정을 다시 검토해야 합니다
                              </Text>
                              <Text className="gng-caption" type="supporting" color="secondary" as="p">
                                {currentness === "stale" ? "결정 이후 비교 입력이 달라졌습니다." : "결정의 현재성을 확인하지 못했습니다."}
                                {" "}이전 결정 기록은 보존되며 새 결정은 덮어쓰지 않고 추가됩니다.
                              </Text>
                            </div>
                          </div>
                        ) : null}

                        {comparisonView && counts ? (
                          <>
                            <section className="gng-delta-overview" aria-label="입찰 변경 비교 집계">
                              <div className="gng-row-line gng-spread">
                                <Heading level={3}>입찰 변경 비교</Heading>
                                <Text className="gng-caption" type="supporting" color="secondary" as="p">
                                  비교 #{comparisonView.sequence} · 버전 {comparisonView.version}
                                </Text>
                              </div>
                              <div className="gng-delta-counts">
                                <div>
                                  <Text className="gng-caption" type="supporting" color="secondary" as="p">중요 변경</Text>
                                  <span className="gng-count-value">
                                    {counts.material}
                                    <span className="gng-caption">건</span>
                                  </span>
                                </div>
                                <div>
                                  <Text className="gng-caption" type="supporting" color="secondary" as="p">비중요 변경</Text>
                                  <span className="gng-count-value">
                                    {counts.nonMaterial}
                                    <span className="gng-caption">건</span>
                                  </span>
                                </div>
                                <div>
                                  <Text className="gng-caption" type="supporting" color="secondary" as="p">확인 필요</Text>
                                  <span className="gng-count-value">
                                    {counts.unresolved}
                                    <span className="gng-caption">건</span>
                                  </span>
                                  <Text className="gng-caption" type="supporting" color="secondary" as="p">unknown·분석 실패</Text>
                                </div>
                              </div>
                              <Text className="gng-caption" type="supporting" color="secondary" as="p">
                                변경 없음 {counts.unchanged}건 · 확인 필요를 변경 없음으로 읽지 않습니다.
                              </Text>
                            </section>

                            <section className="gng-key-changes" aria-label="결정 전에 볼 항목">
                              <div className="gng-row-line gng-spread">
                                <Heading level={3}>결정 전에 볼 항목</Heading>
                                <Text className="gng-caption" type="supporting" color="secondary" as="p">양쪽 문서 비교 결과</Text>
                              </div>
                              {relevantItems.length > 0 ? relevantItems.map((item) => {
                                const page = item.baseline_evidence[0] ?? item.comparison_evidence[0] ?? null;
                                return (
                                  <button
                                    type="button"
                                    className="gng-delta-row"
                                    key={item.id}
                                    onClick={() => { setEvidenceItem(item); setDialog("evidence"); }}
                                  >
                                    <span className="gng-row-line gng-spread">
                                      <Text weight="semibold" as="span">{CATEGORY_LABELS[item.category]}</Text>
                                      <Text className="gng-caption" type="supporting" color="secondary" as="span">{itemKindLabel(item)}</Text>
                                    </span>
                                    <span className="gng-delta-values">
                                      {item.before_value ?? "기준 원문 미확인"}
                                      <ArrowRight aria-hidden="true" />
                                      {item.after_value ?? "비교 원문 미확인"}
                                    </span>
                                    <Text className="gng-caption" type="supporting" color="secondary" as="span">
                                      {page
                                        ? `근거 ${evidenceLocationLabel(page)} · 원문 비교`
                                        : "양쪽 근거가 갖춰지지 않아 변경 여부를 확정하지 못했습니다"}
                                    </Text>
                                  </button>
                                );
                              }) : (
                                <div className="gng-quiet">
                                  <Check aria-hidden="true" />
                                  <Text as="p">양쪽 근거로 확인한 범위에서 결정 전에 볼 변경 항목이 없습니다.</Text>
                                  <Text className="gng-caption" type="supporting" color="secondary" as="p">
                                    변경 없음은 입찰 참여에 대한 추천이 아닙니다.
                                  </Text>
                                </div>
                              )}
                            </section>
                          </>
                        ) : comparisonView ? (
                          <div className="gng-availability">
                            <Clock aria-hidden="true" />
                            <Heading level={3}>
                              {comparisonView.calculation_status === "failed"
                                ? "변경 비교 계산이 실패했습니다"
                                : "변경 비교 계산을 기다리고 있습니다"}
                            </Heading>
                            <Text as="p">
                              {comparisonView.calculation_status === "failed"
                                ? "실패를 변경 없음으로 처리하지 않습니다. 최종 결정은 계산된 결과를 확인한 뒤 기록합니다."
                                : "비교 결과가 나올 때까지 중요 변경과 확인 필요 건수는 미확인으로 남습니다."}
                            </Text>
                            {comparisonView.last_error_code ? (
                              <Text className="gng-caption" type="supporting" color="secondary" as="p">
                                안전한 오류 코드 {comparisonView.last_error_code}
                              </Text>
                            ) : null}
                            <Text className="gng-caption" type="supporting" color="secondary" as="p">
                              변경 비교를 계산하는 프로그램은 아직 운영에 없습니다. 재시도는 결정 화면에서 담당자 이름과 함께 실행합니다.
                            </Text>
                          </div>
                        ) : availability}
                      </>
                    ) : null}

                    {tab === "documents" ? (
                      <section className="gng-documents" aria-label="이번 비교의 기준 문서">
                        <div className="gng-row-line gng-spread">
                          <Heading level={3}>이번 비교의 기준 문서</Heading>
                          <Text className="gng-caption" type="supporting" color="secondary" as="p">{comparisons.length}건의 비교</Text>
                        </div>
                        {comparisons.length > 1 ? (
                          <div className="gng-comparison-picker">
                            <Selector
                              label="표시할 비교"
                              size="sm"
                              value={activeComparison?.id ?? ""}
                              options={comparisons.map((item) => ({
                                value: item.id,
                                label: `비교 #${item.sequence} · 버전 ${item.version}`,
                              }))}
                              onChange={(value) => patchParams({ comparison: value })}
                            />
                            <Text className="gng-caption" type="supporting" color="secondary" as="p">
                              기본값은 요청 순서가 가장 늦은 비교입니다. 새 비교의 문서 쌍은 결정 화면에서 사람이 직접 고릅니다.
                            </Text>
                          </div>
                        ) : null}
                        {comparisonView ? (
                          <>
                            <div className="gng-document-pair">
                              <div>
                                <Text className="gng-caption" type="supporting" color="secondary" as="p">기준 · 사전규격</Text>
                                <Text weight="semibold" as="p">{comparisonView.baseline.notice_external_id}</Text>
                                <Text className="gng-caption" type="supporting" color="secondary" as="p">
                                  문서 버전 {comparisonView.baseline.document_version_version} · 문서 역할 {comparisonView.baseline.document_role || "값 없음"}
                                </Text>
                                <Text className="gng-caption" type="supporting" color="secondary" as="p">
                                  원문 해시 {shortHash(comparisonView.baseline.source_sha256)} · 공개 {formatMoment(comparisonView.baseline.published_at)}
                                </Text>
                              </div>
                              <ArrowRight aria-hidden="true" />
                              <div>
                                <Text className="gng-caption" type="supporting" color="secondary" as="p">대상 · 입찰공고</Text>
                                <Text weight="semibold" as="p">{comparisonView.comparison.notice_external_id}</Text>
                                <Text className="gng-caption" type="supporting" color="secondary" as="p">
                                  문서 버전 {comparisonView.comparison.document_version_version} · 차수 {comparisonView.comparison.bid_ordinal ?? "값 없음"}
                                </Text>
                                <Text className="gng-caption" type="supporting" color="secondary" as="p">
                                  원문 해시 {shortHash(comparisonView.comparison.source_sha256)} · 공개 {formatMoment(comparisonView.comparison.published_at)}
                                </Text>
                              </div>
                            </div>
                            <Text className="gng-caption" type="supporting" color="secondary" as="p">
                              최종 결정은 여기 있는 양쪽 문서 버전과 비교 결과에 연결됩니다. 문서 쌍은 화면이 고르지 않습니다.
                            </Text>
                          </>
                        ) : (
                          <div className="gng-quiet">
                            <Text as="p">아직 선택된 비교 문서가 없습니다.</Text>
                            <Text className="gng-caption" type="supporting" color="secondary" as="p">
                              문서가 없다는 뜻은 아닙니다. 비교에 사용할 양쪽 원문을 결정 화면에서 사람이 고릅니다.
                            </Text>
                          </div>
                        )}
                      </section>
                    ) : null}

                    {tab === "decision" ? (
                      <section className="gng-decision-history" aria-label="사람의 최종 결정">
                        <Heading level={3}>사람의 최종 결정</Heading>
                        {latestDecision ? (
                          <>
                            <div className="gng-history-entry">
                              <div className="gng-row-line gng-spread">
                                <Text weight="semibold" as="span">
                                  {latestDecision.decision === "go" ? "Go · 참여" : "No-Go · 불참"}
                                </Text>
                                <Token
                                  size="sm"
                                  label={currentness === "stale" ? "재검토 필요" : currentness === "unknown" ? "효력 미확인" : "현재 결정"}
                                />
                              </div>
                              <Text as="p">{latestDecision.reason}</Text>
                              <Text className="gng-caption" type="supporting" color="secondary" as="p">
                                {latestDecision.claimed_name} · {formatMoment(latestDecision.created_at)} · 결정 기록 {latestDecision.sequence}
                              </Text>
                            </div>
                            {selectedWorkspace && selectedWorkspace.currentness_reasons.length > 0 ? (
                              <Text className="gng-caption" type="supporting" color="secondary" as="p">
                                현재성 근거 · {selectedWorkspace.currentness_reasons.join(" · ")}
                              </Text>
                            ) : null}
                            <Text className="gng-caption" type="supporting" color="secondary" as="p">
                              이 목록은 사업기회의 마지막 결정만 보여 줍니다. 이전 기록을 포함한 전체 이력은 결정 화면에 있습니다.
                            </Text>
                          </>
                        ) : (
                          <div className="gng-quiet">
                            <Text as="p">
                              {isLoaded(selectedRow) ? "아직 기록된 최종 결정이 없습니다." : "결정 상태를 아직 확인하지 못했습니다."}
                            </Text>
                            <Text className="gng-caption" type="supporting" color="secondary" as="p">
                              추적 상태 ‘계속 추적’은 입찰 참여를 결정했다는 뜻이 아닙니다.
                            </Text>
                          </div>
                        )}
                      </section>
                    ) : null}
                  </div>

                  <footer className="gng-action-footer">
                    <div className="gng-row-line gng-spread">
                      <div className="gng-tracking-summary">
                        <Text className="gng-caption" type="supporting" color="secondary" as="p">현재 사람 결정</Text>
                        <p className="gng-caption">
                          {!isLoaded(selectedRow)
                            ? "미확인"
                            : latestDecision
                              ? `${latestDecision.decision === "go" ? "Go" : "No-Go"} · ${currentness === "current" ? "기록 있음" : currentness === "stale" ? "재검토 필요" : "효력 미확인"}`
                              : "아직 결정하지 않음"}
                        </p>
                      </div>
                      <Button
                        label={canRecordDecision ? "변경 검토·결정 열기" : "비교 상태 확인"}
                        variant="primary"
                        size="sm"
                        icon={<ChevronRight aria-hidden="true" />}
                        onClick={openReview}
                      />
                    </div>
                    <Text className="gng-caption" type="supporting" color="secondary" as="p">
                      {canRecordDecision
                        ? "검토 결과를 확인한 뒤 사람이 Go 또는 No-Go를 선택합니다. 이 목록에서는 저장하지 않습니다."
                        : "계산 완료 전에는 최종 결정을 기록할 수 없습니다. 결정 화면에서 비교 상태와 재시도를 확인합니다."}
                    </Text>
                  </footer>
                </>
              ) : (
                <div className="gng-detail-empty">
                  <Text color="secondary" as="p">선택할 사업이 없습니다.</Text>
                </div>
              )}
            </section>
          </div>
        </>
      ) : null}

      <Dialog isOpen={dialog === "data"} onOpenChange={(open) => { if (!open) setDialog(null); }} purpose="info" width={640}>
        <DialogHeader title="이 목록이 무엇을 세는가" onOpenChange={() => setDialog(null)} />
        <div className="gng-dialog-body" data-astryx-theme="bidops">
          <Text as="p">
            추적 상태가 ‘계속 추적’인 사업기회만 최종 Go/No-Go 대상입니다. 보류·종료·미선택은 이 목록에 올리지 않습니다.
          </Text>
          <Text as="p">
            서버에 결정 목록·집계 endpoint가 없어 페이지 하나(최대 {PAGE_SIZE}건)를 받고 그 행만 사업기회별 결정 상태를
            하나씩 조회합니다. 보기 탭의 건수와 아래 요약은 <strong>받은 페이지 기준</strong>이며 전체 총계가 아닙니다.
          </Text>
          <Text as="p">
            검색은 서버 질의 인자가 없어 받은 페이지 안에서만 좁히는 브라우저 쪽 필터입니다.
          </Text>
          <Text as="p">
            변경 비교를 계산하는 프로그램은 아직 운영에 없습니다. 계산 대기·계산 실패·비교 없음·조회 실패는 모두
            ‘변경 없음’이나 ‘확인 완료’와 다른 상태이며 그대로 표시합니다.
          </Text>
          <Text as="p">
            이 화면은 적합성 등급·참여 준비 상태·심층 추적 승인을 대신하지 않습니다. 최종 결정 저장은 결정 화면에서만 합니다.
          </Text>
          <div className="gng-dialog-actions">
            <Button label="닫기" onClick={() => setDialog(null)} />
          </div>
        </div>
      </Dialog>

      <Dialog isOpen={dialog === "evidence" && evidenceItem !== null} onOpenChange={(open) => { if (!open) setDialog(null); }} purpose="info" width={880}>
        <DialogHeader title="양쪽 원문 근거" onOpenChange={() => setDialog(null)} />
        <div className="gng-dialog-body" data-astryx-theme="bidops">
          {evidenceItem ? (
            <>
              <Heading level={3}>{CATEGORY_LABELS[evidenceItem.category]} · {itemKindLabel(evidenceItem)}</Heading>
              <div className="gng-compare-values">
                <EvidenceSide side="baseline" evidence={evidenceItem.baseline_evidence[0] ?? null} />
                <EvidenceSide side="comparison" evidence={evidenceItem.comparison_evidence[0] ?? null} />
              </div>
              {evidenceItem.baseline_evidence.length + evidenceItem.comparison_evidence.length > 2 ? (
                <Text className="gng-caption" type="supporting" color="secondary" as="p">
                  근거 쌍이 {Math.max(evidenceItem.baseline_evidence.length, evidenceItem.comparison_evidence.length)}개입니다.
                  나머지 쌍과 기술 식별자는 결정 화면의 범주별 분석에 있습니다.
                </Text>
              ) : null}
              {evidenceItem.error_code ? (
                <Text className="gng-caption" type="supporting" color="secondary" as="p">
                  안전한 오류 코드 {evidenceItem.error_code}
                </Text>
              ) : null}
              <Text as="p">
                {evidenceItem.baseline_evidence.length > 0 && evidenceItem.comparison_evidence.length > 0
                  ? "양쪽 문서의 검증된 위치를 그대로 표시합니다."
                  : "양쪽 근거가 갖춰지지 않았습니다. 변경 없음 또는 요건 충족으로 해석하지 않습니다."}
              </Text>
              <div className="gng-dialog-actions">
                <Button label="닫기" onClick={() => setDialog(null)} />
              </div>
            </>
          ) : null}
        </div>
      </Dialog>
    </section>
  );
}

export default GoNoGoPage;
