import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { EmptyState } from "../components/common/EmptyState";
import { ArtifactValidation } from "../components/runs/ArtifactValidation";
import { CollectionScope } from "../components/runs/CollectionScope";
import { ExecutionLog } from "../components/runs/ExecutionLog";
import { PipelineStages } from "../components/runs/PipelineStages";
import { ScreeningRunPanel } from "../components/runs/ScreeningRunPanel";
import { api } from "../lib/api";
import { formatDateTime, formatNumber, formatRunRange, present, runStatusLabel } from "../lib/format";
import type {
  CompanyProfileSnapshotResponse,
  PolicyVersionResponse,
  ProfileSource,
  ScreeningExecutionDetailResponse,
  ScreeningExecutionResponse,
  ScreeningStatus,
  RunSummary,
} from "../lib/types";

type RunnableStage = "collect" | "sample" | "report";

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "수집 실행을 시작하지 못했습니다.";
}

function countFromCollection(run: RunSummary, key: string): number | null {
  const value = run.counts.collection[key];
  return typeof value === "number" ? value : null;
}

function isScreeningTerminal(status: ScreeningStatus | undefined): boolean {
  return status === "성공" || status === "부분 성공" || status === "실패" || status === "중단됨";
}

function profileSourceFor(snapshot: CompanyProfileSnapshotResponse): ProfileSource {
  return snapshot.source_kind === "working_tree" ? "current" : `git:${snapshot.source_ref}`;
}

function screeningActionMessage(error: unknown): string {
  if (error instanceof Error && error.message) return "판정 실행 요청을 처리하지 못했습니다. 입력과 서버 상태를 확인한 뒤 다시 시도해 주세요.";
  return "판정 실행 요청을 처리하지 못했습니다. 다시 시도해 주세요.";
}

/**
 * Poll a single screening execution with a one-shot timer.  The API wrapper
 * owns transport details; the abort signal prevents a late response from
 * updating an unmounted or replaced run panel.
 */
function useScreeningExecutionPoll(executionId: string | null) {
  const [data, setData] = useState<ScreeningExecutionDetailResponse | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!executionId) {
      setData(null);
      setError(null);
      setLoading(false);
      return undefined;
    }

    const controller = new AbortController();
    let timer: number | null = null;
    let inFlight = false;
    let shouldContinue = true;
    setData(null);
    setError(null);

    const schedule = (delay: number) => {
      if (controller.signal.aborted || timer !== null || !shouldContinue) return;
      timer = window.setTimeout(() => {
        timer = null;
        void poll();
      }, delay);
    };

    const poll = async () => {
      if (controller.signal.aborted || inFlight) return;
      inFlight = true;
      setLoading(true);
      try {
        const next = await api.getScreeningExecution(executionId, { signal: controller.signal });
        if (controller.signal.aborted) return;
        setData(next);
        setError(null);
        shouldContinue = !isScreeningTerminal(next.status);
        if (shouldContinue) schedule(1500);
      } catch (nextError) {
        if (controller.signal.aborted) return;
        setError(nextError);
        // Keep a failed detail fetch transient and retry while the execution
        // is still selected; no server error detail is promoted to a status.
        schedule(3000);
      } finally {
        inFlight = false;
        if (!controller.signal.aborted) setLoading(false);
      }
    };

    void poll();
    return () => {
      shouldContinue = false;
      controller.abort();
      if (timer !== null) window.clearTimeout(timer);
    };
  }, [executionId]);

  return { data, error, loading };
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
    queryFn: ({ signal }) => api.getPipelineLogs(selectedRunId as string, undefined, { signal }),
    enabled: Boolean(selectedRunId),
    staleTime: 0,
    refetchInterval: (query) => {
      const data = query.state.data;
      if (!data || !("executions" in data)) return false;
      return data.executions.some((execution) => execution.status === "pending" || execution.status === "running") ? 1000 : false;
    },
  });
  const activationCandidatePoliciesQuery = useQuery({
    queryKey: ["screening-policies", "activation_candidate"],
    queryFn: () => api.getPolicies({ status: "activation_candidate" }),
    staleTime: 30_000,
  });
  const activePoliciesQuery = useQuery({
    queryKey: ["screening-policies", "active"],
    queryFn: () => api.getPolicies({ status: "active" }),
    staleTime: 30_000,
  });
  const profileSnapshotsQuery = useQuery({
    queryKey: ["profile-snapshots"],
    queryFn: api.getProfileSnapshots,
    staleTime: 30_000,
  });
  const screeningExecutionsQuery = useQuery({
    queryKey: ["screening-executions", selectedRunId],
    queryFn: ({ signal }) => api.listScreeningExecutions(
      { run_id: selectedRunId as string, trigger: "manual_run", limit: 25, offset: 0 },
      { signal },
    ),
    enabled: Boolean(selectedRunId),
    staleTime: 0,
    refetchInterval: (query) => {
      const data = query.state.data;
      if (!data) return 1500;
      return data.items.some((execution) => execution.trigger === "manual_run" && execution.scope === "full_run" && !isScreeningTerminal(execution.status)) ? 1500 : false;
    },
  });
  const [actionError, setActionError] = useState<string | null>(null);
  const [activeExecutionId, setActiveExecutionId] = useState<string | null>(null);
  const [screeningActor, setScreeningActor] = useState("");
  const [selectedPolicyVersion, setSelectedPolicyVersion] = useState("");
  const [selectedProfileVersion, setSelectedProfileVersion] = useState("");
  const [screeningExecutionId, setScreeningExecutionId] = useState<string | null>(null);
  const [screeningActionError, setScreeningActionError] = useState<string | null>(null);
  const [screeningStartBusy, setScreeningStartBusy] = useState(false);
  const [screeningStopBusy, setScreeningStopBusy] = useState(false);
  const screeningStartInFlight = useRef(false);
  const screeningStopInFlight = useRef(false);
  const screeningStartOperation = useRef(0);
  const screeningStopOperation = useRef(0);
  const mountedRef = useRef(true);
  const selectedScreeningRunRef = useRef<string | null>(selectedRunId);
  const screeningRunGeneration = useRef(0);
  if (selectedScreeningRunRef.current !== selectedRunId) {
    selectedScreeningRunRef.current = selectedRunId;
    screeningRunGeneration.current += 1;
  }
  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  const policies = useMemo(() => {
    const byVersion = new Map<string, PolicyVersionResponse>();
    [...(activationCandidatePoliciesQuery.data?.items ?? []), ...(activePoliciesQuery.data?.items ?? [])].forEach((policy) => {
      if (!byVersion.has(policy.policy_version)) byVersion.set(policy.policy_version, policy);
    });
    return [...byVersion.values()];
  }, [activationCandidatePoliciesQuery.data, activePoliciesQuery.data]);
  const profileSnapshots = useMemo(() => {
    const byVersion = new Map<string, CompanyProfileSnapshotResponse>();
    (profileSnapshotsQuery.data?.items ?? []).forEach((snapshot) => {
      if (!byVersion.has(snapshot.version)) byVersion.set(snapshot.version, snapshot);
    });
    return [...byVersion.values()];
  }, [profileSnapshotsQuery.data]);
  const screeningExecutions = useMemo(() => screeningExecutionsQuery.data?.items ?? [], [screeningExecutionsQuery.data]);
  const manualFullRunExecutions = useMemo(
    () => screeningExecutions.filter((item) => item.trigger === "manual_run" && item.scope === "full_run"),
    [screeningExecutions],
  );
  const selectedScreeningSummary = manualFullRunExecutions.find((item) => item.execution_id === screeningExecutionId)
    ?? (screeningExecutionId === null ? manualFullRunExecutions[0] : null)
    ?? null;
  const screeningDetailPoll = useScreeningExecutionPoll(screeningExecutionId);
  const selectedPolicy = policies.find((policy) => policy.policy_version === selectedPolicyVersion) ?? null;
  const selectedProfile = profileSnapshots.find((snapshot) => snapshot.version === selectedProfileVersion) ?? null;

  useEffect(() => {
    if (!selectedRunId || selectedRunId === queryRunId) return;
    setSearchParams((current) => {
      const next = new URLSearchParams(current);
      next.set("run", selectedRunId);
      return next;
    }, { replace: true });
  }, [queryRunId, selectedRunId, setSearchParams]);

  useEffect(() => {
    if (!selectedPolicyVersion || !policies.some((policy) => policy.policy_version === selectedPolicyVersion)) {
      setSelectedPolicyVersion(policies[0]?.policy_version ?? "");
    }
  }, [policies, selectedPolicyVersion]);

  useEffect(() => {
    if (!selectedProfileVersion || !profileSnapshots.some((snapshot) => snapshot.version === selectedProfileVersion)) {
      const current = profileSnapshots.find((snapshot) => snapshot.source_kind === "working_tree");
      setSelectedProfileVersion(current?.version ?? profileSnapshots[0]?.version ?? "");
    }
  }, [profileSnapshots, selectedProfileVersion]);

  useEffect(() => {
    // The API returns queue_no-descending order. Prefer the newest active
    // manual full-run execution; when none is active, show the newest one.
    if (screeningExecutionId && !manualFullRunExecutions.some((item) => item.execution_id === screeningExecutionId)) return;
    const preferred = manualFullRunExecutions.find((item) => !isScreeningTerminal(item.status))
      ?? manualFullRunExecutions[0]
      ?? null;
    const nextId = preferred?.execution_id ?? null;
    if (nextId !== screeningExecutionId) setScreeningExecutionId(nextId);
  }, [manualFullRunExecutions, screeningExecutionId]);

  useEffect(() => {
    if (!screeningDetailPoll.data || !screeningExecutionId) return;
    if (isScreeningTerminal(screeningDetailPoll.data.status)) {
      void queryClient.invalidateQueries({ queryKey: ["runs"] });
      void queryClient.invalidateQueries({ queryKey: ["run", selectedRunId] });
      void queryClient.invalidateQueries({ queryKey: ["screening-executions", selectedRunId] });
    }
  }, [queryClient, screeningDetailPoll.data, screeningExecutionId, selectedRunId]);

  useEffect(() => {
    // A run switch should not carry a previous run's execution or transient
    // error into the newly selected original run.
    screeningStartOperation.current += 1;
    screeningStopOperation.current += 1;
    screeningStartInFlight.current = false;
    screeningStopInFlight.current = false;
    setScreeningStartBusy(false);
    setScreeningStopBusy(false);
    setScreeningExecutionId(null);
    setScreeningActionError(null);
  }, [selectedRunId]);

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

  const startScreening = async () => {
    const capturedRunId = selectedRunId;
    const capturedGeneration = screeningRunGeneration.current;
    const hasNonterminalManualFullRun = manualFullRunExecutions.some((item) => !isScreeningTerminal(item.status));
    const screeningListReady = screeningExecutionsQuery.data !== undefined && !screeningExecutionsQuery.isLoading && !screeningExecutionsQuery.error;
    if (screeningStartInFlight.current) return;
    if (!screeningListReady) {
      setScreeningActionError("현재 회차의 판정 실행 목록을 확인하는 중입니다. 목록을 불러온 뒤 다시 시도해 주세요.");
      return;
    }
    if (!capturedRunId || !screeningActor.trim() || !selectedPolicy || !selectedProfile || hasNonterminalManualFullRun) {
      if (hasNonterminalManualFullRun) setScreeningActionError("이미 진행 중인 전량 판정 실행이 있습니다.");
      else setScreeningActionError("담당자 이름, 판정 정책, 프로필 snapshot을 모두 선택해야 합니다.");
      return;
    }
    screeningStartInFlight.current = true;
    const operationToken = ++screeningStartOperation.current;
    setScreeningActionError(null);
    setScreeningStartBusy(true);
    try {
      const execution = await api.enqueueJudgment(capturedRunId, {
        policy_version: selectedPolicy.policy_version,
        profile_source: profileSourceFor(selectedProfile),
        requested_by: screeningActor.trim(),
      });
      const responseIsCurrent = mountedRef.current
        && selectedScreeningRunRef.current === capturedRunId
        && screeningRunGeneration.current === capturedGeneration
        && screeningStartOperation.current === operationToken
        && execution.source_run_id === capturedRunId;
      if (!responseIsCurrent) return;
      setScreeningExecutionId(execution.execution_id);
      void queryClient.invalidateQueries({ queryKey: ["screening-executions", capturedRunId] });
    } catch (error) {
      if (mountedRef.current && selectedScreeningRunRef.current === capturedRunId && screeningRunGeneration.current === capturedGeneration) {
        setScreeningActionError(screeningActionMessage(error));
      }
    } finally {
      if (mountedRef.current && screeningStartOperation.current === operationToken) {
        setScreeningStartBusy(false);
        screeningStartInFlight.current = false;
      }
    }
  };

  const stopScreening = async () => {
    const capturedRunId = selectedRunId;
    const capturedGeneration = screeningRunGeneration.current;
    const capturedExecutionId = screeningExecutionId;
    const latestStatus = screeningDetailPoll.data?.status ?? selectedScreeningSummary?.status;
    if (screeningStopInFlight.current) return;
    if (!capturedRunId || !capturedExecutionId || !screeningActor.trim() || !latestStatus || isScreeningTerminal(latestStatus) || latestStatus === "중지 요청") return;
    screeningStopInFlight.current = true;
    const operationToken = ++screeningStopOperation.current;
    setScreeningActionError(null);
    setScreeningStopBusy(true);
    try {
      const stopped = await api.stopScreeningExecution(capturedExecutionId, { requested_by: screeningActor.trim() });
      const responseIsCurrent = mountedRef.current
        && selectedScreeningRunRef.current === capturedRunId
        && screeningRunGeneration.current === capturedGeneration
        && screeningStopOperation.current === operationToken
        && stopped.source_run_id === capturedRunId;
      if (!responseIsCurrent) return;
      setScreeningExecutionId(stopped.execution_id);
      void queryClient.invalidateQueries({ queryKey: ["screening-executions", capturedRunId] });
    } catch (error) {
      if (mountedRef.current && selectedScreeningRunRef.current === capturedRunId && screeningRunGeneration.current === capturedGeneration) {
        setScreeningActionError(screeningActionMessage(error));
      }
    } finally {
      if (mountedRef.current && screeningStopOperation.current === operationToken) {
        setScreeningStopBusy(false);
        screeningStopInFlight.current = false;
      }
    }
  };

  const selectPublishedRun = (runId: string) => {
    setSearchParams((current) => {
      const next = new URLSearchParams(current);
      next.set("run", runId);
      return next;
    }, { replace: false });
  };

  if (runsQuery.isLoading && runs.length === 0) return <div className="runs-loading" role="status" aria-live="polite">실행 회차를 불러오는 중입니다.</div>;
  if (runsQuery.error) return <EmptyState title="실행 회차를 불러오지 못했습니다." description={errorMessage(runsQuery.error)} action={{ label: "다시 시도", onClick: () => void runsQuery.refetch() }} />;
  if (!selectedRunId) return <EmptyState title="실행 회차가 없습니다." description="수집할 회차가 적재되면 이곳에서 파이프라인을 실행할 수 있습니다." />;
  // 오류일 때도 data가 없으므로, 오류 검사를 로딩 검사보다 먼저 해야 안내가 표시된다.
  if (detailQuery.error) return <EmptyState title="회차 상세를 불러오지 못했습니다." description={errorMessage(detailQuery.error)} action={{ label: "다시 시도", onClick: () => void detailQuery.refetch() }} />;
  if (detailQuery.isLoading || !detailQuery.data) return <div className="runs-loading" role="status" aria-live="polite">선택한 회차의 상세 정보를 불러오는 중입니다.</div>;

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
          <ScreeningRunPanel
            runId={detail.run_id}
            actor={screeningActor}
            onActorChange={setScreeningActor}
            policies={policies}
            policiesLoading={activationCandidatePoliciesQuery.isLoading || activePoliciesQuery.isLoading}
            policiesError={activationCandidatePoliciesQuery.error ?? activePoliciesQuery.error}
            selectedPolicyVersion={selectedPolicyVersion}
            onPolicyChange={setSelectedPolicyVersion}
            profileSnapshots={profileSnapshots}
            profilesLoading={profileSnapshotsQuery.isLoading}
            profilesError={profileSnapshotsQuery.error}
            selectedProfileVersion={selectedProfileVersion}
            onProfileChange={setSelectedProfileVersion}
            selectedProfileSource={selectedProfile ? profileSourceFor(selectedProfile) : null}
            execution={screeningDetailPoll.data}
            executionSummary={selectedScreeningSummary}
            executionLoading={screeningDetailPoll.loading}
            executionError={screeningDetailPoll.error}
            listLoading={screeningExecutionsQuery.isLoading}
            listError={screeningExecutionsQuery.error}
            listReady={screeningExecutionsQuery.data !== undefined}
            onRetryConfiguration={() => {
              void activationCandidatePoliciesQuery.refetch();
              void activePoliciesQuery.refetch();
              void profileSnapshotsQuery.refetch();
              void screeningExecutionsQuery.refetch();
            }}
            onStart={() => void startScreening()}
            startBusy={screeningStartBusy}
            actionError={screeningActionError}
            onStop={() => void stopScreening()}
            stopBusy={screeningStopBusy}
            onOpenPublishedRun={selectPublishedRun}
          />
          <PipelineStages stages={detail.pipeline} counts={selectedSummary.counts} onRun={(stage) => void startStage(stage)} busy={Boolean(logsQuery.data?.executions.some((item) => item.status === "pending" || item.status === "running"))} />
          <div className="runs-two-column"><ArtifactValidation artifacts={detail.artifacts} warningCounts={detail.warning_counts} /><CollectionScope scope={detail.collection_scope} runId={detail.run_id} /></div>
          <ExecutionLog data={logsQuery.data} loading={logsQuery.isLoading} error={logsQuery.error} />
        </section>
      </div>
    </div>
  );
}
