import { useEffect } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Outlet, useLocation, useSearchParams } from "react-router-dom";
import { EmptyState } from "../common/EmptyState";
import { api } from "../../lib/api";
import { Sidebar } from "./Sidebar";
import { TopBar } from "./TopBar";

const pageTitles: Record<string, string> = {
  "/": "대시보드",
  "/queue": "검토 대기열",
  "/deadlines": "마감 추적",
  "/judgments": "공고 판정 이력",
  "/reviews": "담당자 리뷰 기록",
  "/profile": "회사 프로필",
  "/metrics": "검증 지표",
  "/runs": "수집 실행",
  "/attachments": "첨부 확보",
  "/audit": "산출물 감사 로그",
};

function titleForPath(pathname: string): string {
  if (pageTitles[pathname]) return pageTitles[pathname];
  const match = Object.keys(pageTitles).find((path) => path !== "/" && pathname.startsWith(`${path}/`));
  return match ? pageTitles[match] : "BidOps Admin";
}

export function AppShell() {
  const location = useLocation();
  const [searchParams, setSearchParams] = useSearchParams();
  const queryClient = useQueryClient();
  const runsQuery = useQuery({
    queryKey: ["runs"],
    queryFn: api.getRuns,
    staleTime: 30_000,
  });
  const runs = runsQuery.data?.items ?? [];
  const queryRunId = searchParams.get("run");
  // 수집·표본까지만 끝난 회차는 판정이 없어 대부분의 화면이 비어 보인다.
  // 명시적으로 고른 회차가 없으면 판정을 갖춘 최신 회차를 기본으로 삼는다.
  const defaultSummary = runs.find((run) => run.counts.judgments > 0) ?? runs[0] ?? null;
  const selectedSummary = runs.find((run) => run.run_id === queryRunId) ?? defaultSummary;
  const selectedRunId = selectedSummary?.run_id ?? null;
  const detailQuery = useQuery({
    queryKey: ["run", selectedRunId],
    queryFn: () => api.getRun(selectedRunId as string),
    enabled: Boolean(selectedRunId),
    staleTime: 30_000,
  });

  useEffect(() => {
    if (runs.length === 0 || !selectedRunId || queryRunId === selectedRunId) return;
    setSearchParams((current) => {
      const next = new URLSearchParams(current);
      next.set("run", selectedRunId);
      return next;
    }, { replace: true });
  }, [queryRunId, runs.length, selectedRunId, setSearchParams]);

  const onRunChange = (runId: string) => {
    setSearchParams((current) => {
      const next = new URLSearchParams(current);
      next.set("run", runId);
      return next;
    }, { replace: true });
    void queryClient.invalidateQueries();
  };

  const selectedRun = detailQuery.data ?? selectedSummary;
  const runError = runsQuery.error ?? detailQuery.error;

  return (
    <div className="app-shell">
      <Sidebar />
      <div className="app-content">
        <TopBar
          isLoading={runsQuery.isLoading || detailQuery.isLoading}
          onRunChange={onRunChange}
          runs={runs}
          selectedRun={selectedRun}
          selectedRunId={selectedRunId}
          title={titleForPath(location.pathname)}
        />
        {runError ? (
          <div className="shell-notice">
            <EmptyState
              compact
              description={runError instanceof Error ? runError.message : "회차 정보를 확인할 수 없습니다."}
              title="회차 정보를 불러오지 못했습니다."
            />
          </div>
        ) : null}
        <main className="page-canvas">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
