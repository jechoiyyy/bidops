import { useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Outlet, useLocation, useMatches, useSearchParams } from "react-router-dom";
import { EmptyState } from "../common/EmptyState";
import { api } from "../../lib/api";
import "../../styles/shell-relaxed.css";
import { Sidebar } from "./Sidebar";
import { TopBar } from "./TopBar";
import { fallbackRouteMetadata, metadataFromHandle, type RouteMetadata } from "./route-meta";

export function AppShell() {
  const location = useLocation();
  const matches = useMatches();
  const activeRouteMetadata = matches.reduce<RouteMetadata | null>(
    (metadata, match) => metadataFromHandle(match.handle) ?? metadata,
    null,
  ) ?? fallbackRouteMetadata;
  const runContextEnabled = activeRouteMetadata.dataScope === "run";
  const [navOpen, setNavOpen] = useState(false);
  const navRef = useRef<HTMLElement>(null);
  const navTriggerRef = useRef<HTMLButtonElement>(null);
  const navWasOpenRef = useRef(false);
  const [searchParams, setSearchParams] = useSearchParams();
  const queryClient = useQueryClient();
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
    setNavOpen(false);
  }, [location.pathname]);

  // 서랍은 화면을 덮으므로 키보드만 쓰는 담당자도 Esc로 닫을 수 있어야 한다.
  useEffect(() => {
    if (!navOpen) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setNavOpen(false);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [navOpen]);

  // 바깥 클릭·Esc·메뉴 이동으로 서랍이 닫힌 뒤에는 메뉴를 연 조작부로
  // 초점을 돌려 키보드 탐색이 문서 중간으로 이탈하지 않게 한다.
  useEffect(() => {
    if (navOpen) {
      navWasOpenRef.current = true;
      navRef.current?.querySelector<HTMLElement>("a[href]")?.focus({ preventScroll: true });
      return;
    }
    if (!navWasOpenRef.current) return;
    navWasOpenRef.current = false;
    navTriggerRef.current?.focus({ preventScroll: true });
  }, [navOpen]);

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
    <div className="app-shell">
      <Sidebar navRef={navRef} open={navOpen} onClose={() => setNavOpen(false)} />
      <div className="app-content">
        <TopBar
          dataScope={activeRouteMetadata.dataScope}
          editScope={activeRouteMetadata.editScope}
          isLoading={runContextEnabled && (runsQuery.isLoading || detailQuery.isLoading)}
          onToggleNav={() => setNavOpen((current) => !current)}
          menuButtonRef={navTriggerRef}
          navOpen={navOpen}
          onRunChange={onRunChange}
          runSelectorVisible={activeRouteMetadata.runSelectorVisible}
          runs={runs}
          selectedRun={selectedRun}
          selectedRunId={selectedRunId}
          title={activeRouteMetadata.title}
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
