import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate, useSearchParams } from "react-router-dom";
import { Button } from "@astryxdesign/core/Button";
import { Dialog, DialogHeader } from "@astryxdesign/core/Dialog";
import { Heading } from "@astryxdesign/core/Heading";
import { Selector } from "@astryxdesign/core/Selector";
import { Table, pixel, proportional } from "@astryxdesign/core/Table";
import { Text } from "@astryxdesign/core/Text";
import { Token } from "@astryxdesign/core/Token";
import {
  Activity,
  ArrowRight,
  Check,
  ChevronRight,
  Clock,
  RefreshCw,
} from "lucide-react";
import { EmptyState } from "../components/common/EmptyState";
import { PageHeaderActions } from "../components/common/PageHeaderActions";
import {
  AgencyFeature,
  ListPagerControls,
  SplitWorkspace,
  StickyDecisionHeader,
} from "../components/common/ReviewPrimitives";
import { SkeletonPanel } from "../components/common/Skeleton";
import { TechnicalFacts, TechnicalInfo } from "../components/common/TechnicalInfo";
import { useRowKeyboardNavigation } from "../components/common/useRowKeyboardNavigation";
import {
  WorkspaceFilterBar,
  WorkspaceFilterContext,
  WorkspaceFilterLine,
  WorkspaceFrame,
  WorkspaceFilterTools,
  WorkspaceSearch,
  WorkspaceViewTabs,
  formatCount,
} from "../components/common/WorkspaceFilters";
import { getBidDelta, getBidDeltaComparison } from "../components/bid-delta/api";
import {
  BASIS_LABELS,
  CATEGORY_LABELS,
  countDeltaItems,
  decisionRelevantItems,
  defaultComparison,
  decisionBasisDetail,
  itemKindLabel,
  evidenceLocationLabel,
  formatMoment,
} from "../components/bid-delta/labels";
import type {
  BidDeltaComparisonSummary,
  BidDeltaComparisonView,
  BidDeltaEvidenceView,
  BidDeltaItemView,
  BidDeltaWorkspaceView,
} from "../components/bid-delta/types";
import { api } from "../lib/api";
import { describeDeadline, shortDateLabel, type DeadlineUrgency } from "../lib/deadline";
import { formatPrice } from "../lib/format";
import { searchKey, searchMatches } from "../lib/search";
import { apiErrorRecoveryAction, describeApiError } from "../lib/apiErrors";
import type { BidDeltaDecisionQueueItem } from "../lib/types";
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
// 목록은 서버의 결정 대기열(`GET /api/bid-delta/decision-queue`) 한 번으로 그린다
// (spec §11.3). 행의 마지막 결정·현재성·재확인 신호는 그 응답이 준 값이고, 행마다
// workspace를 조회하지 않는다. 선택한 사업 하나의 비교·결정 상세만 따로 받는다.

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

// 결정 대기열이 한 번에 줄 수 있는 최대 건수(서버 `limit` 상한 500). 계속 추적 중인
// 사업은 대개 이보다 적어 보기 건수가 전체 기준이 된다. 넘치면 받은 범위 기준이라고
// 화면이 직접 밝히고 페이저로 나머지를 받는다.
const PAGE_SIZE = 500;

function readOffset(raw: string | null): number {
  const parsed = Number(raw);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : 0;
}

function readView(raw: string | null): DecisionView {
  return VIEWS.some((view) => view.key === raw) ? (raw as DecisionView) : "review";
}

/** 사람이 아는 이름으로 행을 연다. 식별자만 있는 행은 담당자가 무슨 사업인지
 * 알 수 없어 결국 하나씩 열어 봐야 한다(`GoNoGo` 아트보드). */
function opportunityTitle(item: BidDeltaDecisionQueueItem): string {
  return item.title?.trim() || "제목 미확인";
}

function opportunityAgency(item: BidDeltaDecisionQueueItem): string {
  return item.agency?.trim() || "발주기관 미확인";
}

/** 발주기관 줄 끝의 추정가격 한 마디(M5 ④, spec §6.3). 대기열의 `estimated_price`는
 *  반올림 없는 Decimal 문자열이라 표시 직전에만 숫자로 바꾼다(§3.10).
 *  `formatPrice`의 null 표기(`추정가격 미제공`)는 이미 "추정가격" 단어를
 *  포함하므로, 이 줄이 앞에 붙이는 라벨과 겹치지 않게 값이 있을 때만 부른다. */
function estimatedPriceText(item: BidDeltaDecisionQueueItem): string {
  return item.estimated_price === null ? "미제공" : formatPrice(Number(item.estimated_price));
}

/**
 * 입찰 마감 셀(M5 ④, spec §6.3). `describeDeadline`(`lib/deadline.ts`)이 이미
 * 계산한 긴급도·지남 판정을 그대로 쓴다. `describeDeadline`은 목록 두 줄 표시용
 * 이라 7일을 넘으면 D-n 없이 날짜만 주지만, 이 대기열 열은 항상 `D-n · MM-DD`를
 * 적으므로 그 구간의 n은 같은 계산식으로 여기서 마저 구한다 — 새 마감 판정
 * 규칙을 만드는 것이 아니라 이미 쓰는 계산을 한 줄 표기에 맞춰 펼치는 것이다.
 * `null`은 서버가 값을 안 준 것이므로(spec §1.1) `describeDeadline`의
 * `마감 미확인`이 아니라 `마감 미제공`으로 적는다.
 */
function deadlineCellLabel(value: string | null): { text: string; urgency: DeadlineUrgency } {
  const deadline = describeDeadline(value);
  if (!value || deadline.urgency === "none") return { text: "마감 미제공", urgency: "none" };
  if (deadline.urgency === "passed") return { text: deadline.label, urgency: "passed" };
  const days = Math.ceil((new Date(value).getTime() - Date.now()) / 86_400_000);
  const shortDate = shortDateLabel(value);
  return { text: shortDate ? `D-${days} · ${shortDate}` : `D-${days}`, urgency: deadline.urgency };
}

interface DecisionRow extends Record<string, unknown> {
  item: BidDeltaDecisionQueueItem;
  id: number;
}

/**
 * 기본 검토 대상.
 *
 * 미결정만 남기면 **오래된 Go 결정**이 목록에서 사라진다. 새 차수로 현재성이
 * `stale`이 된 결정과 현재성 `unknown`은 담당자가 다시 봐야 하는 것이지 끝난 것이
 * 아니다. 결정이 없어도 입찰공고가 연결되지 않은 사업은 결정할 공고가 없으므로
 * 검토 대상에 올리지 않고 전체 보기에 남긴다.
 */
function isReviewTarget(row: DecisionRow): boolean {
  if (!row.item.latest_final_decision) return row.item.bid_notice_external_id !== null;
  return row.item.decision_currentness !== "current";
}

function isRecheckTarget(row: DecisionRow): boolean {
  return Boolean(row.item.latest_final_decision) && row.item.decision_currentness !== "current";
}

function hasDecisionRecord(row: DecisionRow): boolean {
  return Boolean(row.item.latest_final_decision);
}

function matchesView(row: DecisionRow, view: DecisionView): boolean {
  if (view === "all") return true;
  if (view === "review") return isReviewTarget(row);
  if (view === "recheck") return isRecheckTarget(row);
  return hasDecisionRecord(row);
}

/** 사람 결정 한 줄. 서버 대기열이 준 마지막 결정과 현재성만 옮긴다. */
function decisionStateLabel(item: BidDeltaDecisionQueueItem): string {
  const decision = item.latest_final_decision;
  if (!decision) return "미결정";
  const value = decision.decision === "go" ? "Go" : "No-Go";
  if (item.decision_currentness === "stale") return `${value} · 재검토`;
  if (item.decision_currentness === "unknown") return `${value} · 효력 미확인`;
  return value;
}

function decisionSubLabel(item: BidDeltaDecisionQueueItem): string {
  // 결정이 없으면 현재성은 말할 것이 없다. 기록 없음에 `현재성 미확인`을 덧붙이면
  // 없는 결정이 확인 대기 중인 것처럼 읽힌다.
  if (!item.latest_final_decision) return item.bid_notice_external_id ? "기록 없음" : "입찰공고 미연결";
  if (item.decision_currentness === "stale") return "재검토 필요";
  if (item.decision_currentness === "unknown") return "현재성 미확인";
  return "기록 있음";
}

/** 비교 건수 한 낱말. 비교가 0건인 것은 값이다. 계산 상태는 선택한 사업의 상세가 말한다. */
function comparisonCountLabel(item: BidDeltaDecisionQueueItem): string {
  // 비교 0건을 `비교 0건`으로 눌러 담으면 "아직 안 봤다"와 "봤는데 비교할 것이
  // 없다"가 같은 자리에서 사라진다(PLAN 단계 E 작업 5).
  return item.comparison_count === 0 ? "변경 비교 결과 없음" : `변경 비교 ${item.comparison_count}건`;
}

/** 근거 검증 상태 한 낱말. 서버 enum 원문(`verified`·`missing`·`mismatch`)은
 *  화면에 적지 않는다(ADR-0066 §3.3 한글화) — 값과 URL은 그대로다. */
function verificationLabel(status: BidDeltaEvidenceView["verification_status"]): string {
  if (status === "verified") return "검증됨";
  if (status === "missing") return "근거 없음";
  return "불일치";
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
          근거 검증 · {verificationLabel(evidence.verification_status)}
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
  const [draft, setDraft] = useState(query);
  useEffect(() => setDraft(query), [query]);
  const selectedParam = Number(searchParams.get("selected"));
  const [tab, setTab] = useState<DetailTab>("summary");
  const [dialog, setDialog] = useState<"data" | "evidence" | null>(null);
  const [evidenceItem, setEvidenceItem] = useState<BidDeltaItemView | null>(null);
  /** ↑↓ 키 리스너와 행 탐색의 범위. 표의 스크롤 영역이 모든 행을 담는다. */
  const listRef = useRef<HTMLDivElement>(null);
  const boundaryLandingRef = useRef<{ offset: number; direction: "next" | "previous" } | null>(null);

  // 최종 Go/No-Go까지 가는 것은 계속 추적하기로 한 사업기회다. 서버의 결정 대기열
  // `status=all`이 그 모집단(계속 추적)을 준다. 보기 탭은 받은 행의 결정 필드로 나눈다.
  const queueQuery = useQuery({
    queryKey: ["bid-delta-decision-queue", "all", offset],
    queryFn: ({ signal }) => api.getBidDeltaDecisionQueue({ status: "all", limit: PAGE_SIZE, offset }, { signal }),
    staleTime: 30_000,
  });
  const queueItems = queueQuery.data?.items ?? [];
  const total = queueQuery.data?.total ?? queueItems.length;
  // 받은 범위가 전체인지. 넘치면 보기 건수와 검색은 받은 범위 기준이라고 밝힌다.
  const receivedAll = offset === 0 && queueItems.length >= total;
  const returnSearch = searchParams.toString();

  const rows: DecisionRow[] = queueItems.map((item) => ({ id: item.opportunity_id, item }));

  const trimmedQuery = searchKey(query);
  const scope = trimmedQuery
    ? rows.filter((row) => searchMatches(query, row.item.title, row.item.agency))
    : rows;
  const visibleRows = scope.filter((row) => matchesView(row, view));

  const selectedRow = visibleRows.find((row) => row.id === selectedParam) ?? visibleRows[0];

  // 선택한 사업 **하나의** 비교·결정 상세만 받는다. 목록의 행마다 조회하지 않는다.
  const workspaceQuery = useQuery<BidDeltaWorkspaceView>({
    queryKey: ["bid-delta", selectedRow?.id ?? 0],
    queryFn: () => getBidDelta(selectedRow?.id as number),
    enabled: Boolean(selectedRow),
    staleTime: 30_000,
  });
  const selectedWorkspace = selectedRow ? workspaceQuery.data : undefined;
  const workspaceLoaded = Boolean(selectedWorkspace);
  const comparisons: BidDeltaComparisonSummary[] = selectedWorkspace?.comparisons ?? [];
  const comparisonParam = searchParams.get("comparison");
  const activeComparison = comparisons.find((item) => item.id === comparisonParam)
    ?? defaultComparison(comparisons);

  // 선택한 사업기회의 **선택한 비교 하나만** 상세를 받는다.
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
  const selectedItem = selectedRow?.item ?? null;
  const currentness = selectedItem?.decision_currentness ?? "unknown";
  // 결정 화면의 근거 규칙 그대로다: 완료된 비교(분석 실패 아님)가 있으면 그 결과로,
  // 없으면 연결된 최신 입찰공고의 조건으로 기록한다. 여기서 저장하지 않는다.
  const comparisonBasisReady = Boolean(
    comparisonView
    && comparisonView.calculation_status === "completed"
    && comparisonView.result_status !== "failed",
  );

  function patchParams(patch: Record<string, string | null>) {
    // 사람이 요청한 적 없는 경계 착지는 다른 이동이 끼어드는 순간 유효하지 않다.
    boundaryLandingRef.current = null;
    const params = new URLSearchParams(searchParams);
    for (const [key, value] of Object.entries(patch)) {
      if (value === null || value === "") params.delete(key);
      else params.set(key, value);
    }
    setSearchParams(params, { replace: true });
  }

  function applySearch(value: string) {
    const next = searchKey(value) ? value : "";
    const changed = searchKey(next) !== searchKey(query);
    patchParams({ q: next || null, ...(changed ? { offset: null, selected: null, comparison: null } : {}) });
    setDraft(next);
  }

  function setView(next: DecisionView) {
    // 보는 범위가 달라진다. 옛 선택을 그대로 두면 목록에 없는 행의 상세가 남는다.
    patchParams({ show: next === "review" ? null : next, selected: null, comparison: null });
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

  function goToOffset(next: number, onApplied?: () => void) {
    patchParams({ offset: next > 0 ? String(next) : null, selected: null, comparison: null });
    onApplied?.();
  }

  /**
   * ↑↓ 목록 이동. 리스너는 표의 스크롤 영역이 지고 `rowProps`는 첫 열 버튼이 받는다
   * (발주계획·사전규격·사업 추적과 같은 hook).
   *
   * 이 화면은 저장하는 자리가 없어 이탈 확인이 없다. 경계에서는 대기열 페이지를 넘기고,
   * 페이지를 옮기면 `selected`가 지워져 새 페이지의 첫 행이 선택되므로 `next`는 hook의
   * effect가 초점을 옮긴다. `previous`는 마지막 행에 서야 하므로 아래 effect가 맡는다.
   */
  const rowNavigation = useRowKeyboardNavigation<number>({
    containerRef: listRef,
    keys: visibleRows.map((row) => row.id),
    onBoundary: (direction) => {
      if (direction === "next" && offset + PAGE_SIZE >= total) return;
      if (direction === "previous" && offset === 0) return;
      const targetOffset = direction === "next" ? offset + PAGE_SIZE : Math.max(0, offset - PAGE_SIZE);
      goToOffset(targetOffset, () => {
        boundaryLandingRef.current = { offset: targetOffset, direction };
      });
    },
    onSelect: selectRow,
    selectedKey: selectedRow?.id ?? null,
  });

  // 착지 여부는 ref 하나로 판단하므로 매 렌더 확인한다(`visibleRows`는 렌더마다 새 배열이라
  // 의존성 목록을 적어도 같은 횟수로 돈다). 착지가 없으면 곧바로 빠져나온다.
  useEffect(() => {
    const landing = boundaryLandingRef.current;
    if (!landing || landing.offset !== offset || queueQuery.isPending) return;
    boundaryLandingRef.current = null;
    // 다음 범위에 보기 조건을 지나는 행이 없으면 넘긴 자리에 그대로 둔다.
    if (landing.direction !== "previous" || visibleRows.length === 0) return;
    const lastId = visibleRows[visibleRows.length - 1].id;
    patchParams({ selected: String(lastId), comparison: null });
    requestAnimationFrame(() => {
      listRef.current?.querySelector<HTMLElement>(`[data-row-key="${lastId}"]`)?.focus();
    });
  });

  function openReview() {
    if (!selectedRow) return;
    const search = new URLSearchParams();
    if (activeComparison) search.set("comparison", activeComparison.id);
    if (returnSearch) search.set("back", returnSearch);
    navigate({ pathname: `/opportunities/${selectedRow.id}/bid-delta`, search: search.toString() });
  }

  const queueProblem = queueQuery.error
    ? describeApiError(queueQuery.error, "최종 결정 대기열을 확인할 수 없습니다.")
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
          {...rowNavigation.rowProps(row.id)}
        >
          <Text className="gng-row-title" as="span">{opportunityTitle(row.item)}</Text>
          <Text className="gng-row-agency" as="span">
            {opportunityAgency(row.item)} · 추정가격 {estimatedPriceText(row.item)}
          </Text>
          <Text className="gng-caption" type="supporting" color="secondary" as="span">
            {comparisonCountLabel(row.item)} · 사업기회 {row.id}
          </Text>
        </button>
      ),
    },
    {
      key: "deadline",
      header: "입찰 마감",
      width: pixel(104),
      renderCell: (row: DecisionRow) => {
        const deadline = deadlineCellLabel(row.item.deadline_at);
        return (
          <Text
            className={`gng-deadline-cell mono tabular-nums${deadline.urgency === "critical" ? " gng-deadline-critical" : ""}`}
            as="span"
          >
            {deadline.text}
          </Text>
        );
      },
    },
    {
      key: "decision",
      header: "사람 결정",
      width: pixel(112),
      renderCell: (row: DecisionRow) => (
        <div className="gng-decision-cell">
          <Text className="gng-decision-state" as="span">{decisionStateLabel(row.item)}</Text>
          <Text className="gng-caption" type="supporting" color="secondary" as="span">{decisionSubLabel(row.item)}</Text>
        </div>
      ),
    },
  ];

  const availability = selectedRow && !comparisonView ? (
    <div className="gng-availability">
      <Clock aria-hidden="true" />
      <Heading level={3}>
        {workspaceQuery.isError ? "비교·결정 상세를 불러오지 못했습니다"
          : !workspaceLoaded ? "비교·결정 상세를 확인하고 있습니다"
            : !activeComparison ? "변경 비교 결과가 아직 없습니다"
              : comparisonQuery.isError ? "비교 상세를 불러오지 못했습니다"
                : "비교 상세를 불러오는 중입니다"}
      </Heading>
      {/* 비교가 만들어지지 않는 **이유**(계산 프로그램 미구현)는 `목록 기준`
          다이얼로그 한 곳에서만 말한다(ADR-0066 §3.3). 여기 남는 것은 상태 표식과
          "비교 없음 ≠ 변경 없음"이라는 경고 ④다. */}
      {workspaceLoaded && !activeComparison ? <Token size="sm" label="비교 불가" /> : null}
      <Text as="p">
        {!workspaceLoaded
          ? "조회가 끝나기 전에는 변경 없음으로 표시하지 않습니다. 사람 결정은 목록의 대기열 값 그대로입니다."
          : !activeComparison
            ? "비교가 없다는 것은 변경이 없다는 뜻이 아닙니다."
            : comparisonQuery.isError
              ? "조회 실패를 변경 없음으로 해석하지 않습니다."
              : "결과가 나올 때까지 중요 변경과 확인 필요 건수는 미확인으로 남습니다."}
      </Text>
      {workspaceQuery.isError || comparisonQuery.isError ? (
        <Button
          label="다시 조회"
          size="sm"
          onClick={() => {
            if (workspaceQuery.isError) void workspaceQuery.refetch();
            if (comparisonQuery.isError) void comparisonQuery.refetch();
          }}
        />
      ) : null}
    </div>
  ) : null;

  const footerAction = !selectedItem
    ? null
    : comparisonBasisReady
      ? { label: "변경 검토·결정 열기", note: "검토 결과를 확인한 뒤 사람이 Go 또는 No-Go를 선택합니다. 이 목록에서는 저장하지 않습니다." }
      : selectedItem.bid_notice_external_id
        ? { label: "공고 조건 검토·결정 열기", note: "완료된 변경 비교가 없어 결정 화면에서 최신 입찰공고 조건을 근거로 기록합니다. 이 목록에서는 저장하지 않습니다." }
        : { label: "결정 화면 열기", note: "연결된 입찰공고가 없어 최종 결정을 기록할 수 없습니다. 결정 화면에서 공고 연결 상태를 확인합니다." };

  return (
    <section aria-labelledby="go-no-go-title" className="gng-page" data-astryx-theme="bidops">
      {/* 제목은 상단바(`route-meta.ts`의 제목 모드)가 그린다. 화면은 landmark 이름과
          제목 위계(h1 → h2)를 위해 숨긴 제목만 남기고, 페이지 액션은 상단바 슬롯으로
          보낸다(계획서 §1). 대화상자를 여는 상태는 계속 이 화면이 소유한다. */}
      <h2 className="visually-hidden" id="go-no-go-title">최종 Go/No-Go</h2>
      <PageHeaderActions>
        <div className="gng-header-actions">
          <Button label="목록 기준" variant="ghost" size="sm" icon={<Activity aria-hidden="true" />} onClick={() => setDialog("data")} />
        </div>
      </PageHeaderActions>

      <WorkspaceFrame>
        {/* 필터 골격은 4화면 공용(`components/common/WorkspaceFilters.tsx`)이다.
            필터 집합·URL 파라미터·검색 적용 시점은 그대로 이 화면이 정한다:
            대기열은 이미 받아 둔 목록이지만 검색은 Enter로 적용하고, 상세 필터로
            접을 축이 없어 토글을 두지 않는다(계획서 §2). */}
        <WorkspaceFilterBar aria-label="결정 검토 목록 필터">
          <WorkspaceFilterLine>
            <WorkspaceViewTabs
              className="gng-view-tabs"
              label="결정 검토 보기"
              onChange={setView}
              tabs={VIEWS.map((item) => ({
                key: item.key,
                label: item.label,
                count: scope.filter((row) => matchesView(row, item.key)).length,
              }))}
              value={view}
            />
          </WorkspaceFilterLine>
          <WorkspaceFilterTools className="gng-filter-tools">
            <WorkspaceSearch
              appliedValue={query}
              label="사업명·발주기관 검색"
              onChange={setDraft}
              onClear={() => applySearch("")}
              onEnter={() => applySearch(draft)}
              value={draft}
            />
          </WorkspaceFilterTools>
          <WorkspaceFilterContext className="gng-filter-context">
            <Text className="gng-caption" type="supporting" color="secondary" as="p">
              계속 추적 중인 사업 · 미결정·재검토 포함 · 입찰공고 미연결은 전체 보기에만
              {trimmedQuery && !receivedAll ? " · 검색은 받은 범위 안에서만 좁힙니다" : ""}
            </Text>
            <Text className="gng-caption" type="supporting" color="secondary" as="p">
              {receivedAll
                ? `전체 ${formatCount(total)}건 기준`
                : `받은 ${formatCount(rows.length)}건 기준 · 전체 ${formatCount(total)}건`}
            </Text>
          </WorkspaceFilterContext>
        </WorkspaceFilterBar>

        {/* 목록을 불러오는 중이거나 실패해도 좌우 분할 골격은 그대로 둔다. 화면이
            통째로 접혔다 펴지면 사람이 보던 자리를 잃는다(발주계획·사업 추적과 같은
            규칙). 목록 상태는 목록 pane 안에서 말한다. */}
        <SplitWorkspace
          aria-label="최종 결정 목록과 상세"
          className="gng-workspace"
        >
          <section className="review-split-list gng-list-pane" aria-label="최종 결정 검토 목록">
            <header className="review-list-head gng-list-head">
              {/* 대기열을 못 읽었으면 건수는 0이 아니라 확인 불가다. 조회 중도 0건이 아니다. */}
              <Text className="gng-list-title" as="p">최종 결정 목록 · {queueQuery.isError
                ? "건수 확인 불가"
                : queueQuery.isPending
                  ? "불러오는 중"
                  : `${formatCount(visibleRows.length)}건`}</Text>
              <Text className="gng-caption" type="supporting" color="secondary" as="p">사람 결정 기준</Text>
            </header>
            <div
              className="gng-table-scroll"
              onKeyDown={rowNavigation.onKeyDown}
              onPointerDownCapture={rowNavigation.onPointerDownCapture}
              ref={listRef}
            >
              {queueQuery.isPending ? (
                <SkeletonPanel label="최종 결정 대기열을 불러오는 중" lines={5} />
              ) : queueQuery.isError ? (
                <div className="gng-list-empty">
                  <EmptyState
                    compact
                    tone="error"
                    title="최종 결정 대기열을 불러오지 못했습니다."
                    description="조회 실패를 결정 대기 없음으로 해석하지 않습니다."
                    problem={queueProblem ?? undefined}
                    action={queueProblem
                      ? apiErrorRecoveryAction(queueProblem, () => { void queueQuery.refetch(); })
                      : undefined}
                  />
                </div>
              ) : visibleRows.length > 0 ? (
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
                  <EmptyState
                    compact
                    title="조건에 맞는 사업이 없습니다"
                    description={trimmedQuery
                      ? receivedAll
                        ? `적용된 검색어 "${query}"와 다른 활성 보기 조건에 맞는 사업이 없습니다. 계속 추적 중인 사업 전체에서 찾았습니다.`
                        : `적용된 검색어 "${query}"와 다른 활성 보기 조건에 맞는 사업이 받은 범위에 없습니다. 전체에 없다는 뜻은 아닙니다.`
                      : receivedAll
                        ? "계속 추적 중인 사업 전체에서 찾았습니다. 보기를 바꿔 보십시오."
                        : "받은 범위 안에 없을 뿐, 전체에 없다는 뜻은 아닙니다."}
                    action={{
                      label: trimmedQuery ? "검색어만 지우기" : "필터 초기화",
                      onClick: trimmedQuery ? () => applySearch("") : resetFilters,
                    }}
                  />
                </div>
              )}
            </div>
            {/* 범위 요약과 페이저는 대기열을 읽은 뒤에만 말할 수 있다. 조회 중·실패에
                0건이나 1–0/0을 적으면 "없다"와 "모른다"가 같아진다. */}
            {queueQuery.isPending || queueQuery.isError ? null : (
              <footer className="gng-list-foot">
                {/* 보기 건수는 받은 대기열에서 센 값이다. 한 번에 다 받았으면 전체 기준이고,
                    넘쳐서 나눠 받았으면 그 사실을 여기서 밝힌다. */}
                <p className="gng-summary">
                  {receivedAll
                    ? `전체 ${formatCount(total)}건 기준 · ${formatCount(visibleRows.length)}건 표시`
                    : `받은 ${formatCount(rows.length)}건 기준 · ${formatCount(visibleRows.length)}건 표시 · 전체 ${formatCount(total)}건 중 일부입니다`}
                </p>
                {/* 페이저는 이 범위의 모든 행이 보기 조건에 걸러졌을 때도 남는다.
                    다음 범위로 갈 길까지 사라지면 "없다"와 "이 범위에 없다"가
                    같아진다(발주계획·사전규격과 같은 공용 부품, 명세 §2.2, U3).
                    `total`·`offset`은 서버 페이지 기준이고 `queueItems.length`는
                    받은 페이지의 원본 건수다(view로 좁힌 `visibleRows.length`가
                    아니다) — 대기열 페이지 이동은 view와 무관하기 때문이다. */}
                <ListPagerControls
                  className="gng-pager"
                  label="결정 대기열 페이지"
                  offset={offset}
                  onNext={() => goToOffset(offset + PAGE_SIZE)}
                  onPrevious={() => goToOffset(Math.max(0, offset - PAGE_SIZE))}
                  total={total}
                  visibleCount={queueItems.length}
                />
              </footer>
            )}
          </section>

          <section className="review-split-detail gng-detail-pane" aria-label="선택한 결정 검토 사업">
            {queueQuery.isPending || queueQuery.isError ? (
              <div className="gng-detail-empty">
                <Text color="secondary" as="p">
                  {queueQuery.isPending
                    ? "목록을 불러온 뒤 사업 상세를 표시합니다."
                    : "목록을 불러오지 못해 상세를 표시할 수 없습니다."}
                </Text>
              </div>
            ) : selectedRow && selectedItem ? (
              <>
                {/* 상세 머리는 공용 sticky 머리다(ADR-0062·시안 M1c). 발주기관은 네
                    화면이 같은 강조 블록(`AgencyFeature`)으로 먼저 읽힌다. */}
                <StickyDecisionHeader className="review-detail-head gng-detail-head" label="최종 결정 상세 헤더">
                  <AgencyFeature fallback="발주기관 미확인" name={selectedItem.agency} />
                  <Heading level={2}>{opportunityTitle(selectedItem)}</Heading>
                  <div className="gng-row-line gng-spread">
                    <Text className="gng-caption" type="supporting" color="secondary" as="p">
                      사업기회 {selectedRow.id} · {selectedItem.tracking_status}
                      {" · "}입찰공고 {selectedItem.bid_notice_external_id ?? "미연결"}
                      {selectedItem.recheck_signal ? " · 재확인 신호 있음" : ""}
                    </Text>
                    <Token size="sm" label={decisionStateLabel(selectedItem)} />
                  </div>
                </StickyDecisionHeader>

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
                      {selectedItem.latest_final_decision && currentness !== "current" ? (
                        <div className="gng-review-notice">
                          <RefreshCw aria-hidden="true" />
                          <div>
                            <Text weight="semibold" as="p">
                              기존 {selectedItem.latest_final_decision.decision === "go" ? "Go" : "No-Go"} 결정을 다시 검토해야 합니다
                            </Text>
                            <Text className="gng-caption" type="supporting" color="secondary" as="p">
                              {currentness === "stale" ? "결정 이후 결정의 근거가 달라졌습니다." : "결정의 현재성을 확인하지 못했습니다."}
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
                          {/* 경고 ④는 운영 코드와 한 요소에 두지 않는다 — 코드가
                              접히면서 문장까지 따라 접히면 실패가 조용해진다. */}
                          <Text as="p">
                            {comparisonView.calculation_status === "failed"
                              ? "실패를 변경 없음으로 처리하지 않습니다."
                              : "비교 결과가 나올 때까지 중요 변경과 확인 필요 건수는 미확인으로 남습니다."}
                          </Text>
                          <Token size="sm" label="비교 불가" />
                          {comparisonView.last_error_code ? (
                            <TechnicalInfo summary="기술 정보 · 오류 코드">
                              <TechnicalFacts
                                facts={[{ label: "오류 코드", value: comparisonView.last_error_code }]}
                                label="변경 비교 오류 코드"
                              />
                            </TechnicalInfo>
                          ) : null}
                        </div>
                      ) : availability}
                    </>
                  ) : null}

                  {tab === "documents" ? (
                    <section className="gng-documents" aria-label="이번 비교의 기준 문서">
                      <div className="gng-row-line gng-spread">
                        <Heading level={3}>이번 비교의 기준 문서</Heading>
                        <Text className="gng-caption" type="supporting" color="secondary" as="p">
                          {workspaceLoaded ? `${comparisons.length}건의 비교` : `대기열 기준 ${selectedItem.comparison_count}건의 비교`}
                        </Text>
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
                            기본값은 요청 순서가 가장 늦은 비교입니다.
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
                                공개 {formatMoment(comparisonView.baseline.published_at)}
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
                                공개 {formatMoment(comparisonView.comparison.published_at)}
                              </Text>
                            </div>
                          </div>
                          {/* 문서 버전·공개 일시·문서 역할은 밖에, 해시는 접힌 곳에
                              **전문**으로 둔다(ADR-0066 결정 2, 시안 M4 ③). 같은 문서인지
                              눈으로 대조할 때 펴서 읽는다. */}
                          <TechnicalInfo summary="기술 정보 · 비교 문서 식별자와 해시">
                            <TechnicalFacts
                              facts={[
                                { label: "기준 문서 버전 ID", value: comparisonView.baseline.document_version_id },
                                { label: "기준 원문 해시 SHA-256", value: comparisonView.baseline.source_sha256 },
                                { label: "대상 문서 버전 ID", value: comparisonView.comparison.document_version_id },
                                { label: "대상 원문 해시 SHA-256", value: comparisonView.comparison.source_sha256 },
                              ]}
                              label="비교 문서 식별자와 해시"
                            />
                          </TechnicalInfo>
                          <Text className="gng-caption" type="supporting" color="secondary" as="p">
                            비교 결과 기준 결정은 여기 있는 양쪽 문서 버전과 비교 결과에 연결됩니다. 문서 쌍은 화면이 고르지 않습니다.
                          </Text>
                        </>
                      ) : (
                        <div className="gng-quiet">
                          <Text as="p">아직 선택된 비교 문서가 없습니다.</Text>
                          <Token size="sm" label="비교 불가" />
                          <Text className="gng-caption" type="supporting" color="secondary" as="p">
                            문서가 없다는 뜻은 아닙니다.
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
                              {latestDecision.claimed_name} · {formatMoment(latestDecision.created_at)} · {latestDecision.sequence}번째 결정
                            </Text>
                            <Text className="gng-caption gng-decision-basis" type="supporting" color="secondary" as="p">
                              {BASIS_LABELS[latestDecision.basis_kind]} · {decisionBasisDetail(latestDecision)}
                            </Text>
                          </div>
                          {selectedWorkspace && selectedWorkspace.currentness_reasons.length > 0 ? (
                            <Text className="gng-caption" type="supporting" color="secondary" as="p">
                              현재성 근거 · {selectedWorkspace.currentness_reasons.join(" · ")}
                            </Text>
                          ) : null}
                          <Text className="gng-caption" type="supporting" color="secondary" as="p">
                            이 목록은 사업기회의 마지막 결정만 보여 줍니다. 이전 기록은 결정 화면에서 확인합니다.
                          </Text>
                        </>
                      ) : selectedItem.latest_final_decision ? (
                        <div className="gng-quiet">
                          <Text as="p">
                            {selectedItem.latest_final_decision.decision === "go" ? "Go" : "No-Go"} · {selectedItem.latest_final_decision.claimed_name} · {formatMoment(selectedItem.latest_final_decision.decided_at)}
                          </Text>
                          <Text className="gng-caption" type="supporting" color="secondary" as="p">
                            {workspaceQuery.isError
                              ? "결정 사유와 근거를 불러오지 못했습니다. 검토 요약에서 다시 조회하십시오."
                              : "결정 사유와 근거를 불러오는 중입니다."}
                          </Text>
                        </div>
                      ) : (
                        <div className="gng-quiet">
                          <Text as="p">아직 기록된 최종 결정이 없습니다.</Text>
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
                        {selectedItem.latest_final_decision
                          ? `${selectedItem.latest_final_decision.decision === "go" ? "Go" : "No-Go"} · ${currentness === "current" ? "기록 있음" : currentness === "stale" ? "재검토 필요" : "효력 미확인"}`
                          : "아직 결정하지 않음"}
                      </p>
                    </div>
                    {footerAction ? (
                      <Button
                        label={footerAction.label}
                        variant="primary"
                        size="sm"
                        icon={<ChevronRight aria-hidden="true" />}
                        onClick={openReview}
                      />
                    ) : null}
                  </div>
                  {footerAction ? (
                    <Text className="gng-caption" type="supporting" color="secondary" as="p">
                      {footerAction.note}
                    </Text>
                  ) : null}
                </footer>
              </>
            ) : (
              <div className="gng-detail-empty">
                <Text color="secondary" as="p">선택할 사업이 없습니다.</Text>
              </div>
            )}
          </section>
        </SplitWorkspace>
      </WorkspaceFrame>

      <Dialog isOpen={dialog === "data"} onOpenChange={(open) => { if (!open) setDialog(null); }} purpose="info" width={640}>
        <DialogHeader title="이 목록의 기준" onOpenChange={() => setDialog(null)} />
        <div className="gng-dialog-body" data-astryx-theme="bidops">
          <Text as="p">
            추적 상태가 ‘계속 추적’인 사업기회만 최종 Go/No-Go 대상입니다. 보류·종료·미선택은 이 목록에 올리지 않습니다.
          </Text>
          <Text as="p">
            목록은 서버의 최종 결정 대기열을 한 번 받아 그립니다(한 번에 최대 {PAGE_SIZE}건). 사람 결정·현재성·재확인 신호는
            대기열이 준 값이며 행마다 따로 조회하지 않습니다. 대기열이 {PAGE_SIZE}건을 넘으면 보기 건수와 검색은 받은 범위 기준입니다.
          </Text>
          <Text as="p">
            검토 대상은 입찰공고가 연결된 미결정 사업과, 결정이 있어도 현재성이 ‘현재’가 아닌 사업입니다. 입찰공고가 연결되지 않은
            사업은 결정할 공고가 없어 전체 보기에만 둡니다.
          </Text>
          <Text as="p">
            변경 비교를 계산하는 프로그램은 아직 운영에 없습니다. 최종 결정은 결정 화면에서 최신 입찰공고의 공고 조건을 근거로
            기록할 수 있습니다. 계산 대기·계산 실패·비교 없음·조회 실패는 모두 ‘변경 없음’이나 ‘확인 완료’와 다른 상태이며 그대로 표시합니다.
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
              {/* 해시와 오류 코드는 지우지 않고 접힌 곳으로 모은다(ADR-0066 결정 2).
                  값은 **전문**이며 8자 축약을 만들지 않는다. 모르는 오류 코드도 그대로
                  통과시킨다(결정 3). */}
              <TechnicalInfo
                summary={`기술 정보 · 근거 문서 해시${evidenceItem.error_code ? "와 오류 코드" : ""}`}
              >
                <TechnicalFacts
                  facts={[
                    {
                      label: "기준 사전규격 원문 해시",
                      value: evidenceItem.baseline_evidence[0]?.source_sha256 ?? "값 없음",
                    },
                    {
                      label: "대상 입찰공고 원문 해시",
                      value: evidenceItem.comparison_evidence[0]?.source_sha256 ?? "값 없음",
                    },
                    ...(evidenceItem.error_code
                      ? [{ label: "오류 코드", value: evidenceItem.error_code }]
                      : []),
                  ]}
                  label="근거 문서 해시와 오류 코드"
                />
              </TechnicalInfo>
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
