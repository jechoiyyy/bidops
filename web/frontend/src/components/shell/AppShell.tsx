import { useEffect, useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Outlet, useMatches, useSearchParams } from "react-router-dom";
import { EmptyState } from "../common/EmptyState";
import { api } from "../../lib/api";
import { demoConfigQueryKey, isCompanyUuid } from "../../lib/companyApi";
import { CompanySelector } from "./CompanySelector";
import { Sidebar } from "./Sidebar";
import { applyRecordTitle, RecordTitleContext, RecordTitleSetterContext, type RecordTitleValue } from "./RecordTitleContext";
import { TopBar } from "./TopBar";
import {
  fallbackRouteMetadata,
  metadataFromHandle,
  resolveRouteLocation,
  type RouteMetadata,
} from "./route-meta";

/**
 * `demoEnabled`는 `GET /api/demo-config`의 값이다(`routes.tsx`가 넘긴다). 꺼져 있으면
 * 회사 메뉴·선택기·데모 표식을 그리지 않는다.
 */
export function AppShell({ demoEnabled = false }: { demoEnabled?: boolean }) {
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
  const [recordTitle, setRecordTitle] = useState<RecordTitleValue>(null);
  const location = useMemo(
    () => resolveRouteLocation(activeRouteMetadata, activeMatch?.params ?? {}, searchParams),
    [activeRouteMetadata, activeMatch?.params, searchParams],
  );
  // 사업기회 레코드 페이지가 올린 제목은 같은 사업기회의 경로 칸에만 쓴다(RL-02).
  const crumbs = useMemo(
    () => applyRecordTitle(location.crumbs, activeMatch?.params ?? {}, recordTitle),
    [location.crumbs, activeMatch?.params, recordTitle],
  );
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
    // 회차가 바뀌면 화면 데이터를 다시 읽는다. route 표를 정하는 demo-config는 회차와 무관하고
    // 다시 읽다 실패하면 회사 화면이 사라질 수 있으므로 제외한다.
    void queryClient.invalidateQueries({ predicate: (query) => query.queryKey[0] !== demoConfigQueryKey[0] });
  };

  // 회사는 주소가 정본이다. 회사 route의 `companyId` param만 읽고 기본 회사를 고르지 않는다.
  const companyParam = activeMatch?.params.companyId;
  const activeCompanyId = demoEnabled && isCompanyUuid(companyParam) ? companyParam : null;

  const selectedRun = runContextEnabled ? detailQuery.data ?? selectedSummary : null;
  const runError = runContextEnabled ? runsQuery.error ?? detailQuery.error : null;

  return (
    <div className="app-shell" data-astryx-theme="bidops" data-theme="light">
      <Sidebar
        activeNavPath={location.navPath}
        demoNav={demoEnabled ? { companyId: activeCompanyId } : null}
        runSearch={runSearch}
      />
      <div className="app-content">
        <TopBar
          companyContext={demoEnabled ? <CompanySelector companyId={activeCompanyId} /> : null}
          crumbs={crumbs}
          dataScope={activeRouteMetadata.dataScope}
          isLoading={runContextEnabled && (runsQuery.isLoading || detailQuery.isLoading)}
          onRunChange={onRunChange}
          runSearch={runSearch}
          runSelectorVisible={activeRouteMetadata.runSelectorVisible}
          runs={runs}
          selectedRun={selectedRun}
          selectedRunId={selectedRunId}
          title={activeRouteMetadata.title}
          topbarMode={location.topbarMode}
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
          <RecordTitleSetterContext.Provider value={setRecordTitle}>
            <RecordTitleContext.Provider value={recordTitle}>
              <Outlet />
            </RecordTitleContext.Provider>
          </RecordTitleSetterContext.Provider>
        </main>
      </div>
    </div>
  );
}
