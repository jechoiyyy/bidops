import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { EmptyState } from "../components/common/EmptyState";
import { ArtifactValidation } from "../components/runs/ArtifactValidation";
import { CollectionScope } from "../components/runs/CollectionScope";
import { ExecutionLog } from "../components/runs/ExecutionLog";
import { PipelineStages } from "../components/runs/PipelineStages";
import { api } from "../lib/api";
import { formatDateTime, formatNumber, formatRunRange, present, runStatusLabel } from "../lib/format";
import type { RunSummary } from "../lib/types";

type RunnableStage = "collect" | "sample" | "report";

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "수집 실행을 시작하지 못했습니다.";
}

function countFromCollection(run: RunSummary, key: string): number | null {
  const value = run.counts.collection[key];
  return typeof value === "number" ? value : null;
}

function RunListItem({ run, selected, onSelect }: { run: RunSummary; selected: boolean; onSelect: () => void }) {
  const collected = countFromCollection(run, "total");
  const candidate = countFromCollection(run, "candidate_pool");
  return (
    <button className={`runs-list-item ${selected ? "is-selected" : ""}`.trim()} type="button" onClick={onSelect}>
      <span className="runs-list-item-heading"><strong className="mono">{formatRunRange(run.run_id, run.window_from, run.window_to)}</strong><span className={`runs-status runs-status-${run.status}`}>{runStatusLabel(run.status)}</span></span>
      <span className="runs-list-item-meta">{formatDateTime(run.generated_at)} · <span className="mono">{formatNumber(collected)}</span>건 수집</span>
      <span className="runs-list-item-counts"><span>후보 {formatNumber(candidate)}</span><span>표본 {formatNumber(run.counts.notices)}</span></span>
    </button>
  );
}

export function RunsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const queryClient = useQueryClient();
  const runsQuery = useQuery({ queryKey: ["runs"], queryFn: api.getRuns, staleTime: 5_000 });
  const runs = runsQuery.data?.items ?? [];
  const queryRunId = searchParams.get("run");
  const selectedRunId = runs.some((run) => run.run_id === queryRunId) ? queryRunId : runs[0]?.run_id ?? null;
  const detailQuery = useQuery({
    queryKey: ["run", selectedRunId],
    queryFn: () => api.getRun(selectedRunId as string),
    enabled: Boolean(selectedRunId),
    staleTime: 2_000,
  });
  const logsQuery = useQuery({
    queryKey: ["pipeline-logs", selectedRunId],
    queryFn: () => api.getPipelineLogs(selectedRunId as string),
    enabled: Boolean(selectedRunId),
    staleTime: 0,
    refetchInterval: (query) => {
      const data = query.state.data;
      if (!data || !("executions" in data)) return false;
      return data.executions.some((execution) => execution.status === "pending" || execution.status === "running") ? 1000 : false;
    },
  });
  const [actionError, setActionError] = useState<string | null>(null);
  const [activeExecutionId, setActiveExecutionId] = useState<string | null>(null);

  useEffect(() => {
    if (!selectedRunId || selectedRunId === queryRunId) return;
    setSearchParams((current) => {
      const next = new URLSearchParams(current);
      next.set("run", selectedRunId);
      return next;
    }, { replace: true });
  }, [queryRunId, selectedRunId, setSearchParams]);

  useEffect(() => {
    const execution = logsQuery.data?.executions.find((item) => item.execution_id === activeExecutionId);
    if (!execution || execution.status !== "success") return;
    void queryClient.invalidateQueries({ queryKey: ["runs"] });
    void queryClient.invalidateQueries({ queryKey: ["run", selectedRunId] });
    if (execution.result_run_id && execution.result_run_id !== selectedRunId) {
      setSearchParams((current) => {
        const next = new URLSearchParams(current);
        next.set("run", execution.result_run_id as string);
        return next;
      }, { replace: true });
    }
  }, [activeExecutionId, logsQuery.data, queryClient, selectedRunId, setSearchParams]);

  const selectRun = (runId: string) => {
    setSearchParams((current) => {
      const next = new URLSearchParams(current);
      next.set("run", runId);
      return next;
    }, { replace: true });
  };

  const startStage = async (stage: RunnableStage, fromRaw = false) => {
    if (!selectedRunId) return;
    setActionError(null);
    try {
      const execution = await api.runPipeline(selectedRunId, stage, fromRaw);
      setActiveExecutionId(execution.execution_id);
      await queryClient.invalidateQueries({ queryKey: ["pipeline-logs", selectedRunId] });
    } catch (error) {
      setActionError(errorMessage(error));
    }
  };

  if (runsQuery.isLoading && runs.length === 0) return <div className="runs-loading">실행 회차를 불러오는 중입니다.</div>;
  if (runsQuery.error) return <EmptyState title="실행 회차를 불러오지 못했습니다." description={errorMessage(runsQuery.error)} />;
  if (!selectedRunId) return <EmptyState title="실행 회차가 없습니다." description="수집할 회차가 적재되면 이곳에서 파이프라인을 실행할 수 있습니다." />;
  if (detailQuery.isLoading || !detailQuery.data) return <div className="runs-loading">선택한 회차의 상세 정보를 불러오는 중입니다.</div>;
  if (detailQuery.error) return <EmptyState title="회차 상세를 불러오지 못했습니다." description={errorMessage(detailQuery.error)} />;

  const detail = detailQuery.data;
  const selectedSummary = runs.find((run) => run.run_id === selectedRunId) ?? detail;
  return (
    <div className="runs-page">
      <header className="runs-page-header">
        <div><div className="runs-eyebrow">운영 · 파이프라인</div><h2>수집 실행 관리</h2><p>기존 수집 스크립트를 실행하고 산출물 적재 결과를 확인합니다.</p></div>
        <div className="runs-actions">
          <button className="runs-secondary-button" type="button" onClick={() => void startStage("collect", true)} disabled={Boolean(logsQuery.data?.executions.some((item) => item.status === "pending" || item.status === "running"))}>
            원문 재분류 실행 <code>--from-raw</code>
          </button>
          <button className="runs-primary-button" type="button" onClick={() => void startStage("collect")} disabled={Boolean(logsQuery.data?.executions.some((item) => item.status === "pending" || item.status === "running"))}>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" aria-hidden="true"><path d="M12 5v14M5 12h14" /></svg>
            새 회차 수집
          </button>
        </div>
      </header>
      {actionError ? <p className="runs-error" role="alert">{actionError}</p> : null}
      <div className="runs-layout">
        <aside className="runs-list" aria-label="실행 회차 목록">
          <div className="runs-list-heading"><span>실행 회차</span><span className="mono">{runs.length}건</span></div>
          {runs.map((run) => <RunListItem key={run.run_id} run={run} selected={run.run_id === selectedRunId} onSelect={() => selectRun(run.run_id)} />)}
        </aside>
        <section className="runs-detail">
          <div className="runs-detail-heading"><div><span className="runs-eyebrow">선택한 회차</span><h3 className="mono">{formatRunRange(detail.run_id, detail.window_from, detail.window_to)}</h3><p>{formatDateTime(detail.generated_at)} · {present(detail.screening_basis, "판정 기준 미기록")}</p></div><span className={`runs-status runs-status-${detail.status}`}>{runStatusLabel(detail.status)}</span></div>
          <PipelineStages stages={detail.pipeline} counts={selectedSummary.counts} onRun={(stage) => void startStage(stage)} busy={Boolean(logsQuery.data?.executions.some((item) => item.status === "pending" || item.status === "running"))} />
          <div className="runs-two-column"><ArtifactValidation artifacts={detail.artifacts} warningCounts={detail.warning_counts} /><CollectionScope scope={detail.collection_scope} runId={detail.run_id} /></div>
          <ExecutionLog data={logsQuery.data} loading={logsQuery.isLoading} error={logsQuery.error} />
        </section>
      </div>
    </div>
  );
}
