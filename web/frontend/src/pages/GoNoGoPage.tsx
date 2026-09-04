import { useQueries, useQuery } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router-dom";
import { Badge } from "@astryxdesign/core/Badge";
import { Banner } from "@astryxdesign/core/Banner";
import { Heading } from "@astryxdesign/core/Heading";
import { Text } from "@astryxdesign/core/Text";
import { ToggleButton, ToggleButtonGroup } from "@astryxdesign/core/ToggleButton";
import { EmptyState } from "../components/common/EmptyState";
import { getBidDelta } from "../components/bid-delta/api";
import type { BidDeltaWorkspaceView, Currentness } from "../components/bid-delta/types";
import { api } from "../lib/api";
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

function currentnessLabel(value: Currentness): string {
  if (value === "current") return "최신";
  if (value === "stale") return "재계산 필요";
  return "unknown (확인 대기)";
}

function currentnessVariant(value: Currentness): "success" | "warning" | "neutral" {
  if (value === "current") return "success";
  if (value === "stale") return "warning";
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
  if (row.isPending) return <Badge variant="neutral" label="결정 상태 확인 중" />;
  if (row.isError) return <Badge variant="error" label="결정 상태 조회 실패" />;

  const workspace = row.workspace;
  if (!workspace) return <Badge variant="neutral" label="결정 상태 unknown" />;

  const decision = workspace.latest_final_decision;
  return (
    <>
      {decision ? (
        <Badge variant={decision.decision === "go" ? "success" : "neutral"} label={`결정 ${decision.decision}`} />
      ) : (
        <Badge variant="warning" label="결정 대기" />
      )}
      <Badge variant={currentnessVariant(workspace.decision_currentness)} label={currentnessLabel(workspace.decision_currentness)} />
      {/* 비교가 0건인 것은 값이다. `비교 0건`으로 눌러 담으면 "아직 안 봤다"와
          "봤는데 비교할 것이 없다"가 같은 자리에서 사라진다(PLAN 단계 E 작업 5). */}
      {workspace.comparisons.length === 0 ? (
        <Badge variant="warning" label="변경 비교 결과 없음" />
      ) : (
        <Badge variant="neutral" label={`비교 ${workspace.comparisons.length}건`} />
      )}
    </>
  );
}

export function GoNoGoPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const filter: DecisionFilter = searchParams.get("show") === "all" ? "all" : "pending";

  // 최종 Go/No-Go까지 가는 것은 계속 추적하기로 한 사업기회다. 보류·종료·미선택을
  // 결정 대기로 끌어올리지 않는다.
  const opportunitiesQuery = useQuery({
    queryKey: ["opportunities", "tracking", "계속 추적"],
    queryFn: ({ signal }) => api.getOpportunities({ tracking_status: "계속 추적", limit: 100 }, { signal }),
    staleTime: 30_000,
  });
  const opportunities = opportunitiesQuery.data?.items ?? [];
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

  function setFilter(next: DecisionFilter) {
    const params = new URLSearchParams(searchParams);
    if (next === "all") params.set("show", "all");
    else params.delete("show");
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
        <Banner
          status="error"
          title="추적 중인 사업기회를 불러오지 못했습니다."
          description="조회 실패를 결정 대기 없음으로 해석하지 않습니다."
          collapsible={false}
        />
      ) : null}

      {opportunitiesQuery.isPending ? (
        <Text type="body" color="secondary" as="p" role="status">추적 중인 사업기회를 불러오는 중…</Text>
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
    </section>
  );
}
