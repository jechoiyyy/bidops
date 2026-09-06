import { useQueries, useQuery } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router-dom";
import { Heading } from "@astryxdesign/core/Heading";
import { Text } from "@astryxdesign/core/Text";
import { ToggleButton, ToggleButtonGroup } from "@astryxdesign/core/ToggleButton";
import { Badge, type BadgeVariant } from "../components/common/Badge";
import { EmptyState } from "../components/common/EmptyState";
import { SkeletonBlock, SkeletonPanel } from "../components/common/Skeleton";
import { getBidDelta } from "../components/bid-delta/api";
import type { BidDeltaWorkspaceView, Currentness } from "../components/bid-delta/types";
import { api } from "../lib/api";
import { apiErrorRecoveryAction, describeApiError } from "../lib/apiErrors";
import type { OpportunityListItem } from "../lib/types";
import "../styles/criteria-runstatus.css";

// docs/design/PLAN.md 2단계 · ADR-0041 결정 3: 최종 Go/No-Go를 최상위 메뉴로
// 올린다. 빈도는 낮아도 되돌릴 수 없는 결정이며, 지금까지 사이드바에서 도달할
// 길이 없이 /opportunities/:id/bid-delta 안에만 있었다.
//
// 이 화면은 결정 화면이 아니라 **결정 대기 목록**이다. 실제 Go/No-Go는 계속
// BidDeltaDecisionPage에서만 내린다. 적합성 등급·참여 준비 상태·심층 추적
// 승인을 이 화면에서 대신 채우지 않는다(ADR-0041 결정 5).
//
// 서버에 결정 목록 엔드포인트가 없다(routers/bid_delta.py는 사업기회 하나의
// workspace만 준다). 2단계는 백엔드를 바꾸지 않으므로 추적 중인 사업기회를
// 먼저 받고 각 행의 결정 상태를 행 단위로 조회한다. 조회 전 상태를 "결정 없음"
// 으로 단정하지 않고 확인 대기로 표시한다.

type DecisionFilter = "pending" | "all";

// 한 화면이 사업기회 100건을 받고 **행마다** workspace를 하나씩 조회했다 —
// 최대 101 요청이다. 서버에 결정 목록 엔드포인트가 없다는 사실은 그대로지만,
// 한 번에 보는 만큼만 받으면 행 조회도 그만큼으로 줄어든다. 페이지 크기를
// 줄이고 페이저를 두어 **화면에 있는 행만** workspace를 조회한다.
const PAGE_SIZE = 25;

function readOffset(raw: string | null): number {
  const parsed = Number(raw);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : 0;
}

function currentnessLabel(value: Currentness): string {
  if (value === "current") return "최신";
  if (value === "stale") return "재계산 필요";
  return "unknown (확인 대기)";
}

function currentnessVariant(value: Currentness): BadgeVariant {
  if (value === "current") return "success";
  // 재계산이 필요한 상태는 실패가 아니라 경고다.
  if (value === "stale") return "alert";
  return "neutral";
}

/** 사람이 아는 이름으로 행을 연다. 식별자만 있는 행은 담당자가 무슨 사업인지
 * 알 수 없어 결국 하나씩 열어 봐야 한다(`GoNoGo` 아트보드). */
function opportunityTitle(item: OpportunityListItem): string {
  const named = item.links.find((link) => link.title && link.title.trim());
  return named?.title?.trim() ?? "제목 미확인";
}

function opportunityMarker(item: OpportunityListItem): string {
  const evidence = item.links.find((link) => link.evidence_bid_no ?? link.evidence_external_no);
  const marker = evidence?.evidence_bid_no ?? evidence?.evidence_external_no;
  const agency = item.links.find((link) => link.agency && link.agency.trim())?.agency?.trim();
  return [agency ?? "기관 미확인", `사업기회 ${item.id}`, marker].filter(Boolean).join(" · ");
}

interface DecisionRow {
  opportunity: OpportunityListItem;
  workspace: BidDeltaWorkspaceView | undefined;
  isPending: boolean;
  isError: boolean;
}

/** 결정 기록이 아직 없으면 결정 대기다. 조회가 끝나지 않았거나 실패한 행은
 * 어느 쪽으로도 단정하지 않고 목록에 남긴다. */
function isAwaitingDecision(row: DecisionRow): boolean {
  if (row.isPending || row.isError) return true;
  return !row.workspace?.latest_final_decision;
}

function DecisionBadges({ row }: { row: DecisionRow }) {
  // 조회 전이라는 사실은 배지 문구가 말하고, 그 옆의 골격은 자리를 잡아 준다.
  // 골격에 live region을 또 붙이면 행 수만큼 같은 문장을 되풀이해 읽는다.
  if (row.isPending) {
    return (
      <>
        <Badge variant="neutral" label="결정 상태 확인 중" />
        <SkeletonBlock className="skeleton-inline" label={null} lines={1} />
      </>
    );
  }
  if (row.isError) return <Badge variant="danger" label="결정 상태 조회 실패" />;

  const workspace = row.workspace;
  if (!workspace) return <Badge variant="neutral" label="결정 상태 unknown" />;

  const decision = workspace.latest_final_decision;
  return (
    <>
      {decision ? (
        <Badge variant={decision.decision === "go" ? "success" : "neutral"} label={`결정 ${decision.decision}`} />
      ) : (
        <Badge variant="alert" label="결정 대기" />
      )}
      <Badge variant={currentnessVariant(workspace.decision_currentness)} label={currentnessLabel(workspace.decision_currentness)} />
      {/* 비교가 0건인 것은 값이다. `비교 0건`으로 눌러 담으면 "아직 안 봤다"와
          "봤는데 비교할 것이 없다"가 같은 자리에서 사라진다(PLAN 단계 E 작업 5). */}
      {workspace.comparisons.length === 0 ? (
        <Badge variant="alert" label="변경 비교 결과 없음" />
      ) : (
        <Badge variant="neutral" label={`비교 ${workspace.comparisons.length}건`} />
      )}
    </>
  );
}

export function GoNoGoPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const filter: DecisionFilter = searchParams.get("show") === "all" ? "all" : "pending";
  const offset = readOffset(searchParams.get("offset"));

  // 최종 Go/No-Go까지 가는 것은 계속 추적하기로 한 사업기회다. 보류·종료·미선택을
  // 결정 대기로 끌어올리지 않는다.
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
      queryKey: ["bid-delta", "workspace", item.id],
      queryFn: () => getBidDelta(item.id),
      staleTime: 30_000,
    })),
  });

  const rows: DecisionRow[] = opportunities.map((opportunity, index) => ({
    opportunity,
    workspace: workspaceQueries[index]?.data,
    isPending: workspaceQueries[index]?.isPending ?? true,
    isError: workspaceQueries[index]?.isError ?? false,
  }));
  const visibleRows = filter === "pending" ? rows.filter(isAwaitingDecision) : rows;
  const opportunitiesProblem = opportunitiesQuery.error
    ? describeApiError(opportunitiesQuery.error, "추적 중인 사업기회 목록을 확인할 수 없습니다.")
    : null;

  function setFilter(next: DecisionFilter) {
    const params = new URLSearchParams(searchParams);
    if (next === "all") params.set("show", "all");
    else params.delete("show");
    // 필터를 바꾸면 보는 범위가 달라진다. 옛 페이지 위치를 그대로 두면 빈
    // 페이지가 열린다.
    params.delete("offset");
    setSearchParams(params, { replace: true });
  }

  function goToOffset(next: number) {
    const params = new URLSearchParams(searchParams);
    if (next > 0) params.set("offset", String(next));
    else params.delete("offset");
    setSearchParams(params, { replace: true });
  }

  return (
    <section aria-labelledby="go-no-go-title" className="gng-page" data-astryx-theme="bidops">
      <header className="gng-head">
        <Heading level={2} id="go-no-go-title">최종 Go/No-Go</Heading>
        <Text type="body" color="secondary" as="p">
          결정 대기 중인 사업기회입니다. 결정은 사업기회마다 입찰 변경 비교 화면에서 내리며 되돌릴 수 없습니다.
          이 목록은 적합성 등급·참여 준비 상태·심층 추적 승인을 대신하지 않습니다.
        </Text>
        <ToggleButtonGroup
          type="single"
          label="결정 상태 필터"
          value={filter}
          onChange={(value) => setFilter(value === "all" ? "all" : "pending")}
        >
          <ToggleButton value="pending" label="결정 대기" />
          <ToggleButton value="all" label="추적 중 전체" />
        </ToggleButtonGroup>
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

      {!opportunitiesQuery.isPending && !opportunitiesQuery.isError && visibleRows.length === 0 ? (
        <div className="gng-empty">
          <EmptyState
            title={filter === "pending" ? "결정 대기 중인 사업기회가 없습니다." : "계속 추적 중인 사업기회가 없습니다."}
            description="추적 상태가 계속 추적인 사업기회만 최종 Go/No-Go 대상입니다. 보류·종료·미선택을 결정 대기로 올리지 않습니다."
          />
        </div>
      ) : null}

      {visibleRows.length > 0 ? (
        <>
        <p className="gng-summary">
          {/* 상단 요약은 받은 목록에서 센 값이다. 서버가 결정 상태를 집계하지 않으므로
              전체 총계로 읽으면 안 된다(docs/tracking/findings.md). */}
          받은 {rows.length.toLocaleString("ko-KR")}건 기준 · 결정 대기 {rows.filter(isAwaitingDecision).length.toLocaleString("ko-KR")} ·
          {" "}Go {rows.filter((row) => row.workspace?.latest_final_decision?.decision === "go").length.toLocaleString("ko-KR")} ·
          {" "}No-Go {rows.filter((row) => row.workspace?.latest_final_decision?.decision === "no_go").length.toLocaleString("ko-KR")}.
          서버가 결정 상태를 집계하지 않아 전체 총계가 아닙니다.
        </p>
        <div className="gng-list">
          {visibleRows.map((row) => (
            <Link
              className="gng-row"
              key={row.opportunity.id}
              to={{ pathname: `/opportunities/${row.opportunity.id}/bid-delta`, search: returnSearch }}
            >
              <span className="gng-row-line">
                <Text type="body" color="primary">{opportunityTitle(row.opportunity)}</Text>
                <span className="gng-row-badges"><DecisionBadges row={row} /></span>
              </span>
              <Text type="supporting" color="secondary" as="span">{opportunityMarker(row.opportunity)}</Text>
              <Text type="supporting" color="secondary" as="span">
                추적 {row.opportunity.tracking_status} · 최초 등록 단계 {row.opportunity.first_registered_stage}
                {row.opportunity.recheck_signal ? " · 재확인 신호 있음" : ""}
              </Text>
            </Link>
          ))}
        </div>
        </>
      ) : null}

      {/* 페이저는 목록이 비어 보이는 페이지에서도 남는다. 이 페이지의 모든 행이
          결정 대기 필터에 걸러졌다고 해서 다음 페이지로 갈 길까지 사라지면
          "없다"와 "이 페이지에 없다"가 같아진다. */}
      {!opportunitiesQuery.isPending && !opportunitiesQuery.isError && total > PAGE_SIZE ? (
        <nav
          aria-label="사업기회 목록 페이지"
          style={{ display: "flex", alignItems: "center", gap: "var(--spacing-3)" }}
        >
          <button
            className="interaction-control"
            type="button"
            disabled={offset === 0}
            onClick={() => goToOffset(Math.max(0, offset - PAGE_SIZE))}
          >
            이전
          </button>
          <Text type="supporting" color="secondary" as="span">
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
    </section>
  );
}
