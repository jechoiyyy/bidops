import { useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Outlet, useLocation, useSearchParams } from "react-router-dom";
import { EmptyState } from "../common/EmptyState";
import { api } from "../../lib/api";
import "../../styles/shell-relaxed.css";
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

// 화면마다 무엇을 고칠 수 있는지가 다르다. 전역 "읽기 전용"은 실제 동작과 맞지 않았다.
const editScopes: Record<string, string> = {
  "/queue": "리뷰 저장 가능",
  "/judgments": "판정 원문 읽기 전용",
  "/profile": "원본 문서에서 관리",
};

function editScopeForPath(pathname: string): string | null {
  const match = Object.keys(editScopes).find((path) => pathname === path || pathname.startsWith(`${path}/`));
  return match ? editScopes[match] : null;
}

function titleForPath(pathname: string): string {
  if (pageTitles[pathname]) return pageTitles[pathname];
  const match = Object.keys(pageTitles).find((path) => path !== "/" && pathname.startsWith(`${path}/`));
  return match ? pageTitles[match] : "BidOps Admin";
}

export function AppShell() {
  const location = useLocation();
  const [navOpen, setNavOpen] = useState(false);
  const navTriggerRef = useRef<HTMLButtonElement>(null);
  const navWasOpenRef = useRef(false);
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
      return;
    }
    if (!navWasOpenRef.current) return;
    navWasOpenRef.current = false;
    navTriggerRef.current?.focus({ preventScroll: true });
  }, [navOpen]);

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
      <Sidebar open={navOpen} onClose={() => setNavOpen(false)} />
      <div className="app-content">
        <TopBar
          editScope={editScopeForPath(location.pathname)}
          isLoading={runsQuery.isLoading || detailQuery.isLoading}
          onToggleNav={() => setNavOpen((current) => !current)}
          menuButtonRef={navTriggerRef}
          navOpen={navOpen}
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
