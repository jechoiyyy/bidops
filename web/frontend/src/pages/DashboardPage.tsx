import { Link, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Button } from "@astryxdesign/core/Button";
import { Selector } from "@astryxdesign/core/Selector";
import { Text } from "@astryxdesign/core/Text";
import { InternationalizationProvider } from "@astryxdesign/core/i18n";
import koKR from "@astryxdesign/core/locales/ko-KR.json";
import { Activity, ArrowRight, ArrowUpRight, RefreshCw } from "lucide-react";
import { api } from "../lib/api";
import { formatNumber } from "../lib/format";
import { PageHeaderActions } from "../components/common/PageHeaderActions";
import { DashboardState, LinkButton, Small, Tag } from "../components/dashboard/DashboardPrimitives";
import { DeadlinePanel, SummaryPanel, ValidationPanel, VerificationPanel } from "../components/dashboard/DashboardPanels";
import { deadlineFilter, runLink, runOptionLabel, snapshotTime } from "../components/dashboard/dashboardData";
import "../styles/dashboard-erp.css";

// Approved HTML/TSX/CSS is the layout source. Only API data and SPA navigation
// replace its fixtures. Cumulative tasks do not depend on a selected run.
export function DashboardPage() {
  return <InternationalizationProvider locale="ko-KR" messages={{ "ko-KR": koKR }}><DashboardWorkspace /></InternationalizationProvider>;
}

function DashboardWorkspace() {
  const [params, setParams] = useSearchParams();
  const runId = params.get("run")?.trim() || null;
  const filter = deadlineFilter(params.get("deadline"));
  const runsQuery = useQuery({ queryKey: ["runs"], queryFn: api.getRuns, staleTime: 30_000 });
  const statsQuery = useQuery({ queryKey: ["run-stats", runId], queryFn: () => api.getRunStats(runId!), enabled: Boolean(runId), staleTime: 30_000 });
  const validationQuery = useQuery({ queryKey: ["validation-metrics", runId], queryFn: () => api.getValidationMetrics(runId!), enabled: Boolean(runId), staleTime: 30_000 });
  const candidatesQuery = useQuery({
    queryKey: ["dashboard-action", "order-plan-review-candidates"],
    queryFn: async ({ signal }) => {
      const [relevant, uncertain] = await Promise.all([
        api.getOrderPlans({ qwen_relevance: "relevant", limit: 1 }, { signal }),
        api.getOrderPlans({ qwen_relevance: "uncertain", limit: 1 }, { signal }),
      ]);
      return relevant.total + uncertain.total;
    }, staleTime: 60_000,
  });
  const runs = runsQuery.data?.items ?? [];
  const selectedRun = runs.find(run => run.run_id === runId);
  const stats = statsQuery.data;
  const reference = statsQuery.isError ? "기준 시각 미확인" : snapshotTime(stats?.generated_at, stats?.timezone);
  const timezone = stats?.timezone === "Asia/Seoul" ? "KST" : stats?.timezone ?? "";
  const noRun = !runId;
  const candidateNote = candidatesQuery.isError ? "검토 후보 건수 미확인" : candidatesQuery.isPending ? "검토 후보 확인 중" : `검토 후보 ${formatNumber(candidatesQuery.data)}건 · 누적`;
  const setRun = (value: string) => setParams(current => {
    const next = new URLSearchParams(current);
    if (value) next.set("run", value); else next.delete("run");
    next.delete("deadline");
    return next;
  });
  const setFilter = (value: string) => setParams(current => {
    const next = new URLSearchParams(current);
    if (value === "week") next.delete("deadline"); else next.set("deadline", value);
    return next;
  });
  const refresh = () => {
    void candidatesQuery.refetch(); void runsQuery.refetch();
    if (runId) { void statsQuery.refetch(); void validationQuery.refetch(); }
  };
  const isRefreshing = candidatesQuery.isFetching || runsQuery.isFetching || statsQuery.isFetching || validationQuery.isFetching;

  return <section className="dash-page" aria-label="대시보드" data-astryx-theme="bidops">
    <PageHeaderActions><div className="dash-header-actions"><Button label="새로고침" size="sm" variant="ghost" icon={<RefreshCw aria-hidden="true" />} isDisabled={isRefreshing} onClick={refresh} /><LinkButton label="실행 상태" to={runLink("/run-status", runId)} icon={<Activity aria-hidden="true" />} secondary /></div></PageHeaderActions>
    <nav className="dash-journey-strip" aria-label="업무 바로가기 · 회차와 무관한 누적 업무">
      {[
        ["01", "발주계획", "추적할 후보 선택", candidateNote, "/order-plans"],
        ["02", "사전규격", "검토 결과·추적 여부 확인", "결정 대기 건수 미확인", "/pre-specs?sort=deadline"],
        ["03", "사업 추적", "연결·예외 사항 확인", "조치 필요 건수 미확인", "/opportunities?section=조치 필요"],
        ["04", "최종 Go/No-Go", "입찰 참여 여부 결정", "결정 대기 건수 미확인", "/go-no-go"],
      ].map(([step, title, action, note, to]) => <Link key={step} className="dash-journey-item" to={to}>
        <div className="dash-row dash-spread"><div className="dash-row"><Small>{step}</Small><Text weight="semibold" className="dash-journey-title">{title}</Text></div><ArrowUpRight aria-hidden="true" /></div>
        <Text>{action}</Text><Small>{note}</Small>
      </Link>)}
    </nav>

    <section className="dash-run-context" aria-label="회차 자료 범위">
      <div className="dash-row"><Text weight="semibold">회차 자료</Text><Selector label="조회할 실행 회차" isLabelHidden size="sm" value={runId ?? ""} onChange={setRun} hasSearch searchPlaceholder="회차 검색" emptySearchText="일치하는 회차가 없습니다"
        options={[{ value: "", label: "회차 선택 안 함" }, ...runs.map(run => ({ value: run.run_id, label: runOptionLabel(run), description: run.run_id })), ...(runId && !selectedRun ? [{ value: runId, label: runId, description: runsQuery.isError ? "회차 목록 조회 실패" : "목록에서 회차를 확인할 수 없음" }] : [])]}
        placeholder={runsQuery.isPending ? "회차 목록 조회 중" : "회차 선택"} /><Tag label="읽기 전용" /></div>
      <div className="dash-row dash-context-end"><Small>{noRun ? "회차를 선택해 주세요" : `${reference}${stats && !statsQuery.isError ? ` 기준 · ${timezone}` : ""}`}</Small><LinkButton label="회차 실행 보기" to={runLink("/runs", runId)} icon={<ArrowRight aria-hidden="true" />} /></div>
    </section>
    {runsQuery.isError && <div className="dash-runs-error" role="alert"><Text>회차 목록을 불러오지 못했습니다.</Text><Button label="회차 목록 다시 조회" size="sm" onClick={() => { void runsQuery.refetch(); }} /></div>}

    {noRun ? <DashboardState kind={runsQuery.isPending ? "loading" : "empty"} title={runsQuery.isPending ? "회차 목록을 불러오는 중입니다" : "확인할 회차를 선택해 주세요"}
      action={<LinkButton label="공고 판정 이력" to="/queue" />}>
      {runsQuery.isSuccess && runs.length === 0 ? "표시할 회차가 없습니다. " : "위의 회차 선택기에서 공고 판정 이력을 열 수 있습니다. "}상단의 네 업무는 회차 선택과 관계없이 이용할 수 있습니다.
    </DashboardState> : statsQuery.isError ? <DashboardState kind="error" title="회차 자료를 불러오지 못했습니다" action={<Button label="회차 자료 다시 조회" icon={<RefreshCw aria-hidden="true" />} onClick={() => { void statsQuery.refetch(); }} />}>
      건수와 상태를 확인할 수 없습니다. 상단의 업무 바로가기는 계속 이용할 수 있습니다.
    </DashboardState> : statsQuery.isPending || !stats ? <DashboardState kind="loading" title="회차 자료를 불러오는 중입니다">마감 공고와 검증 결과를 확인하고 있습니다.</DashboardState>
      : <div className="dash-dashboard-grid" key={runId}>
        <DeadlinePanel stats={stats} filter={filter} onFilterChange={setFilter} />
        <VerificationPanel requests={stats.verification_requests} runId={runId} />
        <SummaryPanel stats={stats} reviewCount={runsQuery.isError ? undefined : selectedRun?.counts.reviews} />
        <ValidationPanel metrics={validationQuery.data?.metrics ?? []} isPending={validationQuery.isPending} isError={validationQuery.isError} onRetry={() => { void validationQuery.refetch(); }} runId={runId} auditMissed={stats.audit_missed_count} />
      </div>}
    <footer className="dash-dashboard-foot"><Small>마감과 집계는 선택한 회차의 기준 시각을 따릅니다. 최종 참여 판단은 최종 Go/No-Go에서 진행합니다.</Small></footer>
  </section>;
}
