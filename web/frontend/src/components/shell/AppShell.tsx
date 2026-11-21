import { latestNoticeRun } from "../../lib/orderPlanDaily";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Outlet, useLocation, useMatches, useSearchParams } from "react-router-dom";
import { EmptyState } from "../common/EmptyState";
import { api } from "../../lib/api";
import { demoConfigQueryKey, isCompanyUuid } from "../../lib/companyApi";
import { CompanySelector } from "./CompanySelector";
import { Sidebar } from "./Sidebar";
import { currentPageHeader, PageHeaderSetterContext, type PageHeaderContent, type PublishedPageHeader } from "./PageHeaderContext";
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
  // 화면이 올린 패널 헤더 글자(`usePageHeader`). 올린 화면의 pathname과 함께 둔다.
  const { pathname } = useLocation();
  const [publishedHeader, setPublishedHeader] = useState<PublishedPageHeader | null>(null);
  const publishHeader = useCallback((key: string, content: PageHeaderContent | null) => {
    setPublishedHeader((current) => {
      if (content) return { pathname: key, content };
      return current?.pathname === key ? null : current;
    });
  }, []);
  const pageHeader = currentPageHeader(publishedHeader, pathname);
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
  const noticeDefault = ["/judgments", "/queue", "/reviews", "/deadlines", "/attachments"].includes(pathname) ? latestNoticeRun(runs) : null;
  const defaultSummary = noticeDefault ?? runs.find((run) => run.counts.judgments > 0) ?? runs[0] ?? null;
  const selectedSummary = runs.find((run) => run.run_id === queryRunId) ?? defaultSummary;
  const selectedRunId = selectedSummary?.run_id ?? null;
  const detailQuery = useQuery({
    queryKey: ["run", selectedRunId],
    queryFn: () => api.getRun(selectedRunId as string),
    enabled: runContextEnabled && Boolean(selectedRunId),
    staleTime: 30_000,
  });

  // 공고 상세(`/judgments/:noticePk`·`/queue/:noticePk`)를 회차 없이 연 링크는 상세가 자기 회차를
  // 정한다(설계고도화안 C-5). 셸이 먼저 기본 회차를 박으면 그 회차 목록에 없는 공고가 다른 공고로
  // 바뀌거나 남의 회차 맥락으로 보이므로, 주소에 회차가 없는 공고 상세에서는 기본 회차를 넣지 않는다.
  const noticeDetailWithoutRun = Boolean(activeMatch?.params.noticePk) && !queryRunId;
  useEffect(() => {
    if (noticeDetailWithoutRun) return;
    if (!runContextEnabled || runs.length === 0 || !selectedRunId || queryRunId === selectedRunId) return;
    setSearchParams((current) => {
      const next = new URLSearchParams(current);
      next.set("run", selectedRunId);
      return next;
    }, { replace: true });
  }, [noticeDetailWithoutRun, queryRunId, runContextEnabled, runs.length, selectedRunId, setSearchParams]);

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
      {/* 본문은 바탕(frame) 위에 뜬 흰 패널 하나다(2026-11-19 최종 시안). 패널 헤더 → 본문. */}
      {/* `data-reading-width`: 상세 본문·헤더 안쪽·하단 띠를 읽기 폭 가운데에 맞추는 화면(route metadata). */}
      <div className="app-content" data-reading-width={location.readingWidth ? "detail" : undefined} data-shell-region="panel">
        <TopBar
          companyContext={demoEnabled ? <CompanySelector companyId={activeCompanyId} /> : null}
          crumbs={crumbs}
          pageHeader={pageHeader}
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
              description={runError instanceof Error ? runError.message : "회차 정보를 확인할 수 없어요."}
              title="회차 정보를 불러오지 못했어요"
            />
          </div>
        ) : null}
        <main className="page-canvas" data-canvas={location.canvas} data-shell-region="canvas">
          <PageHeaderSetterContext.Provider value={publishHeader}>
            <RecordTitleSetterContext.Provider value={setRecordTitle}>
              <RecordTitleContext.Provider value={recordTitle}>
                <Outlet />
              </RecordTitleContext.Provider>
            </RecordTitleSetterContext.Provider>
          </PageHeaderSetterContext.Provider>
        </main>
        {/* 패널 아래 고정 띠 portal 슬롯(`PageFooterBar`). 본문 스크롤 밖이라 읽는 동안 늘 같은 자리에 있다.
            비어 있으면 CSS가 접어 높이가 0이고 다른 화면의 배치는 바뀌지 않는다. */}
        <div className="page-footer" data-shell-region="footer" id="page-footer" />
      </div>
    </div>
  );
}
