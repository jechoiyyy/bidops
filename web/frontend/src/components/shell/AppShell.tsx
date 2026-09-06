import { useEffect } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Outlet, useMatches, useSearchParams } from "react-router-dom";
import { EmptyState } from "../common/EmptyState";
import { api } from "../../lib/api";
import { Sidebar } from "./Sidebar";
import { TopBar } from "./TopBar";
import {
  fallbackRouteMetadata,
  metadataFromHandle,
  resolveRouteLocation,
  type RouteMetadata,
} from "./route-meta";

export function AppShell() {
  const matches = useMatches();
  const activeMatch = matches.reduce<{ metadata: RouteMetadata; params: Readonly<Record<string, string | undefined>> } | null>(
    (current, match) => {
      const metadata = metadataFromHandle(match.handle);
      return metadata ? { metadata, params: match.params } : current;
    },
    null,
  );
  const activeRouteMetadata = activeMatch?.metadata ?? fallbackRouteMetadata;
  const runContextEnabled = activeRouteMetadata.dataScope === "run";
  const [searchParams, setSearchParams] = useSearchParams();
  const queryClient = useQueryClient();
  const location = resolveRouteLocation(activeRouteMetadata, activeMatch?.params ?? {}, searchParams);
  // 회차 선택은 주소의 run 파라미터에만 남아 있다. 셸이 만드는 이동 링크는
  // 모두 이 값을 그대로 넘겨 담당자가 고른 회차를 잃지 않게 한다.
  const runSearch = searchParams.has("run") ? `?run=${encodeURIComponent(searchParams.get("run") ?? "")}` : "";
  const runsQuery = useQuery({
    queryKey: ["runs"],
    queryFn: api.getRuns,
    enabled: runContextEnabled,
    staleTime: 30_000,
  });
  const runs = runContextEnabled ? runsQuery.data?.items ?? [] : [];
  const queryRunId = searchParams.get("run");
  // 수집·표본까지만 끝난 회차는 판정이 없어 대부분의 화면이 비어 보인다.
  // 명시적으로 고른 회차가 없으면 판정을 갖춘 최신 회차를 기본으로 삼는다.
  const defaultSummary = runs.find((run) => run.counts.judgments > 0) ?? runs[0] ?? null;
  const selectedSummary = runs.find((run) => run.run_id === queryRunId) ?? defaultSummary;
  const selectedRunId = selectedSummary?.run_id ?? null;
  const detailQuery = useQuery({
    queryKey: ["run", selectedRunId],
    queryFn: () => api.getRun(selectedRunId as string),
    enabled: runContextEnabled && Boolean(selectedRunId),
    staleTime: 30_000,
  });

  useEffect(() => {
    if (!runContextEnabled || runs.length === 0 || !selectedRunId || queryRunId === selectedRunId) return;
    setSearchParams((current) => {
      const next = new URLSearchParams(current);
      next.set("run", selectedRunId);
      return next;
    }, { replace: true });
  }, [queryRunId, runContextEnabled, runs.length, selectedRunId, setSearchParams]);

  const onRunChange = (runId: string) => {
    setSearchParams((current) => {
      const next = new URLSearchParams(current);
      next.set("run", runId);
      return next;
    }, { replace: true });
    void queryClient.invalidateQueries();
  };

  const selectedRun = runContextEnabled ? detailQuery.data ?? selectedSummary : null;
  const runError = runContextEnabled ? runsQuery.error ?? detailQuery.error : null;

  return (
    <div className="app-shell" data-astryx-theme="bidops" data-theme="light">
      <Sidebar activeNavPath={location.navPath} runSearch={runSearch} />
      <div className="app-content">
        <TopBar
          crumbs={location.crumbs}
          dataScope={activeRouteMetadata.dataScope}
          editScope={activeRouteMetadata.editScope}
          isLoading={runContextEnabled && (runsQuery.isLoading || detailQuery.isLoading)}
          onRunChange={onRunChange}
          runSearch={runSearch}
          runSelectorVisible={activeRouteMetadata.runSelectorVisible}
          runs={runs}
          selectedRun={selectedRun}
          selectedRunId={selectedRunId}
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
        <main className="page-canvas" data-shell-region="canvas">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
