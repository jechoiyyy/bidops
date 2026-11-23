import { latestNoticeRun } from "../lib/orderPlanDaily";
import { useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { useLocation, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { EmptyState } from "../components/common/EmptyState";
import { NoticeRecord } from "../components/notice/NoticeRecord";
import { NoticeRunTable } from "../components/notice/NoticeRunTable";
import { api, ApiError } from "../lib/api";

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback;
}

export function NoticeDetailPage() {
  const location = useLocation();
  const navigate = useNavigate();
  const { noticePk: noticePkParam } = useParams();
  const [searchParams, setSearchParams] = useSearchParams();
  const runsQuery = useQuery({ queryKey: ["runs"], queryFn: api.getRuns, staleTime: 30_000 });
  const selectedId = noticePkParam && Number.isInteger(Number(noticePkParam)) ? Number(noticePkParam) : null;
  const keepListOpen = Boolean((location.state as { keepListOpen?: boolean } | null)?.keepListOpen);
  const detailQuery = useQuery({
    queryKey: ["notice", selectedId],
    queryFn: () => api.getNotice(selectedId as number),
    enabled: selectedId !== null,
    staleTime: 30_000,
  });
  /**
   * 회차는 주소의 `run`이 먼저다. 주소에 회차가 없이 공고를 연 링크(사업기회 레코드·추적 흐름)는
   * **그 공고 상세가 알려 준 회차**를 쓴다 — 기본 회차의 목록에 그 공고가 없다는 이유로 다른 공고로
   * 바꾸지 않는다(설계고도화안 C-5). 공고를 고르지 않았을 때만 최신 회차를 기본으로 둔다.
   */
  const detailRunId = detailQuery.data?.id === selectedId ? detailQuery.data?.run_id ?? null : null;
  const runs = runsQuery.data?.items ?? [];
  const recentNotices = latestNoticeRun(runs);
  const runId = searchParams.get("run")
    ?? (selectedId !== null ? detailRunId : recentNotices?.run_id ?? runs[0]?.run_id ?? null);

  useEffect(() => {
    if (searchParams.get("run") || !runId) return;
    const next = new URLSearchParams(searchParams);
    next.set("run", runId);
    setSearchParams(next, { replace: true });
  }, [runId, searchParams, setSearchParams]);

  const noticesQuery = useQuery({
    queryKey: ["judgment-notices", runId],
    queryFn: () => api.getNotices({ run_id: runId as string, grade: "all", sample_role: "all", sort: "published", limit: 500, offset: 0 }),
    enabled: Boolean(runId),
    staleTime: 30_000,
  });

  const notices = noticesQuery.data?.items ?? [];
  const detail = detailQuery.data?.id === selectedId ? detailQuery.data : undefined;

  // 공고를 고르지 않고 들어왔을 때만 목록의 첫 공고를 고른다. 고른 공고가 이 회차 목록(최대 500건)에
  // 없더라도 **다른 공고로 바꾸지 않는다** — 상세는 공고 번호로 따로 읽는다(설계고도화안 C-5).
  useEffect(() => {
    if (!runId || noticesQuery.isLoading || notices.length === 0) return;
    if (selectedId === null && !keepListOpen) {
      navigate({ pathname: `/judgments/${notices[0].id}`, search: searchParams.toString() }, { replace: true, state: null });
    }
  }, [keepListOpen, navigate, notices, noticesQuery.isLoading, runId, searchParams, selectedId]);

  const selectNotice = (id: number) => navigate({ pathname: `/judgments/${id}`, search: searchParams.toString() }, { state: null });

  if (runsQuery.error) {
    return <EmptyState title="회차 정보를 불러오지 못했어요" description={errorMessage(runsQuery.error, "회차를 확인할 수 없어요.")} />;
  }
  if (selectedId !== null && !runId) {
    // 회차 없이 연 공고 상세: 상세가 회차를 알려 줄 때까지 기다리고, 공고가 없으면 다른 공고로
    // 바꾸지 않고 찾을 수 없다고 말한다(설계고도화안 C-5).
    if (detailQuery.isPending) return <p className="rec-status" role="status">공고 상세를 불러오는 중이에요.</p>;
    if (detailQuery.isError && detailQuery.error instanceof ApiError && detailQuery.error.status === 404) {
      return <EmptyState title={`공고 ${selectedId}을(를) 찾을 수 없어요.`} description="없는 공고 번호이거나 지워진 공고예요. 다른 공고로 대신 보여 주지 않아요." />;
    }
    if (detailQuery.isError) {
      return <EmptyState title="공고 상세를 불러오지 못했어요" description={errorMessage(detailQuery.error, "상세 정보를 확인할 수 없어요.")} action={{ label: "다시 시도", onClick: () => void detailQuery.refetch() }} />;
    }
  }
  if (!runId) {
    return <EmptyState title="선택된 회차가 없어요" description="상단의 실행 회차 선택기에서 회차를 선택해 주세요." />;
  }
  if (noticesQuery.error) {
    return <EmptyState title="회차 공고 목록을 불러오지 못했어요" description={errorMessage(noticesQuery.error, "공고 목록을 확인할 수 없어요.")} action={{ label: "다시 시도", onClick: () => void noticesQuery.refetch() }} />;
  }

  return (
    <div className="notice-read-workspace">
      <NoticeRunTable
        detailNote={notices.some((notice) => notice.id === selectedId) ? "선택됨" : "선택 필요"}
        label="회차 공고 목록"
        listNote="회차 공고"
        notices={notices}
        onSelect={selectNotice}
        selectedId={selectedId}
        state={noticesQuery.isLoading ? { kind: "loading", label: "공고 목록을 불러오는 중이에요.", showLabel: true }
          : notices.length === 0 ? {
            kind: "empty",
            message: {
              title: "회차 공고가 없어요",
              description: runs.find((run) => run.run_id === runId)?.kind === "order_plans" ? "이 회차는 발주계획 수집 회차예요." : undefined,
              action: recentNotices && recentNotices.run_id !== runId
                ? { label: "최근 공고 회차 보기", to: `/judgments?run=${encodeURIComponent(recentNotices.run_id)}` }
                : undefined,
            },
          } : undefined}
        total={noticesQuery.data?.total ?? notices.length}
      />
      <section className="notice-read-detail" aria-label="공고 상세">
        {selectedId === null ? (
          <EmptyState title="공고를 선택해 주세요" description="왼쪽 회차 목록에서 공고를 선택하면 생애주기와 판정 이력이 표시돼요." />
        ) : detailQuery.isLoading ? (
          <p role="status">공고 상세와 판정 이력을 불러오는 중이에요.</p>
        ) : detailQuery.error ? (
          <EmptyState title="공고 상세를 불러오지 못했어요" description={errorMessage(detailQuery.error, "상세 정보를 확인할 수 없어요.")} action={{ label: "다시 시도", onClick: () => void detailQuery.refetch() }} />
        ) : !detail ? (
          <EmptyState title="공고 상세가 없어요" description="선택한 공고의 상세 데이터를 확인할 수 없어요." />
        ) : <NoticeRecord notice={detail} />}
      </section>
    </div>
  );
}
