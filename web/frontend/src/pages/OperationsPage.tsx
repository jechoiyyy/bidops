import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { EmptyState } from "../components/common/EmptyState";
import { AlwaysOnPanel } from "../components/operations/AlwaysOnPanel";
import { ScheduleExecutionForm } from "../components/operations/ScheduleExecutionForm";
import { ScheduleExecutionTable } from "../components/operations/ScheduleExecutionTable";
import { ScheduleSettingsForm } from "../components/operations/ScheduleSettingsForm";
import { operationsWriteError } from "../components/operations/feedback";
import { api } from "../lib/api";
import type { ScheduleExecutionCreateRequest, ScheduleExecutionSummary } from "../lib/types";

const operationsQueryKeys = {
  settings: ["operations", "schedule-settings"],
  alwaysOn: ["operations", "always-on"],
  executions: ["operations", "schedule-executions"],
  policies: ["operations", "policies"],
} as const;

async function refreshOperationsReads(
  queryClient: ReturnType<typeof useQueryClient>,
  queryKeys: readonly (readonly string[])[],
): Promise<void> {
  // A conflict can still commit a rejection/disable/audit projection. Read
  // every related projection immediately; failures here must not mask the
  // original write outcome or leave an unhandled promise.
  await Promise.all(queryKeys.map(async (queryKey) => {
    try {
      await queryClient.invalidateQueries({ queryKey, refetchType: "active" });
    } catch {
      // The next safe polling cycle can retry a read that is temporarily down.
    }
  }));
}

function useSafeOperationsPolling(queryClient: ReturnType<typeof useQueryClient>) {
  const inFlight = useRef(false);

  useEffect(() => {
    let disposed = false;
    let timer: number | undefined;

    const poll = async () => {
      if (disposed || inFlight.current) return;
      inFlight.current = true;
      try {
        // One awaited batch is used for all reads. The guard prevents a slow
        // response from overlapping the next cycle, and cleanup prevents a
        // timer from updating an unmounted screen.
        await Promise.all([
          queryClient.invalidateQueries({ queryKey: operationsQueryKeys.settings }),
          queryClient.invalidateQueries({ queryKey: operationsQueryKeys.alwaysOn }),
          queryClient.invalidateQueries({ queryKey: operationsQueryKeys.executions }),
          queryClient.invalidateQueries({ queryKey: operationsQueryKeys.policies }),
        ]);
      } finally {
        inFlight.current = false;
        if (!disposed) timer = window.setTimeout(() => void poll(), 15_000);
      }
    };

    timer = window.setTimeout(() => void poll(), 15_000);
    return () => {
      disposed = true;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [queryClient]);
}

export function OperationsPage() {
  const queryClient = useQueryClient();
  useSafeOperationsPolling(queryClient);
  const settingsQuery = useQuery({ queryKey: operationsQueryKeys.settings, queryFn: api.getScheduleSettings, staleTime: 0 });
  const alwaysOnQuery = useQuery({ queryKey: operationsQueryKeys.alwaysOn, queryFn: api.getAlwaysOn, staleTime: 0 });
  const executionsQuery = useQuery({ queryKey: operationsQueryKeys.executions, queryFn: () => api.getScheduleExecutions({ limit: 100, offset: 0 }), staleTime: 0 });
  const policiesQuery = useQuery({ queryKey: operationsQueryKeys.policies, queryFn: () => api.getPolicies(), staleTime: 0 });
  const [settingsBusy, setSettingsBusy] = useState(false);
  const [alwaysOnBusy, setAlwaysOnBusy] = useState(false);
  const [executionBusy, setExecutionBusy] = useState(false);
  const [recoveryTarget, setRecoveryTarget] = useState<ScheduleExecutionSummary | null>(null);
  const [actionMessage, setActionMessage] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const settingsWriteInFlight = useRef(false);
  const alwaysOnWriteInFlight = useRef(false);
  const executionWriteInFlight = useRef(false);

  const activePolicy = useMemo(
    () => policiesQuery.data?.items.find((policy) => policy.status === "active") ?? null,
    [policiesQuery.data],
  );
  const activePolicyVersion = policiesQuery.data?.active_policy_version ?? null;

  const saveSettings = async (payload: { daily_time: string; weekly_time: string; prespec_enabled: boolean; updated_by: string }): Promise<boolean> => {
    if (settingsWriteInFlight.current) return false;
    settingsWriteInFlight.current = true;
    setSettingsBusy(true);
    setActionError(null);
    setActionMessage(null);
    try {
      await api.updateScheduleSettings(payload);
      await refreshOperationsReads(queryClient, Object.values(operationsQueryKeys));
      setActionMessage("정기 실행 설정을 저장했습니다.");
      return true;
    } catch (error) {
      setActionError(operationsWriteError(error, "settings"));
      await refreshOperationsReads(queryClient, Object.values(operationsQueryKeys));
      return false;
    } finally {
      setSettingsBusy(false);
      settingsWriteInFlight.current = false;
    }
  };

  const updateAlwaysOn = async (payload: { enabled: boolean; confirmed_by: string; quality_gate_result_id: string | null }): Promise<boolean> => {
    if (alwaysOnWriteInFlight.current) return false;
    alwaysOnWriteInFlight.current = true;
    setAlwaysOnBusy(true);
    setActionError(null);
    setActionMessage(null);
    try {
      await api.updateAlwaysOn(payload);
      await refreshOperationsReads(queryClient, Object.values(operationsQueryKeys));
      setActionMessage(payload.enabled ? "상시 운영을 켰습니다." : "상시 운영을 껐습니다. 기존 실행·산출물은 보존됩니다.");
      return true;
    } catch (error) {
      setActionError(operationsWriteError(error, "always_on"));
      await refreshOperationsReads(queryClient, Object.values(operationsQueryKeys));
      return false;
    } finally {
      setAlwaysOnBusy(false);
      alwaysOnWriteInFlight.current = false;
    }
  };

  const submitExecution = async (payload: ScheduleExecutionCreateRequest): Promise<boolean> => {
    if (executionWriteInFlight.current) return false;
    executionWriteInFlight.current = true;
    setExecutionBusy(true);
    setActionError(null);
    setActionMessage(null);
    try {
      await api.createManualScheduleExecution(payload);
      await refreshOperationsReads(queryClient, Object.values(operationsQueryKeys));
      setRecoveryTarget(null);
      setActionMessage(payload.recovery_of_execution_id ? "명시 복구를 예약했습니다." : "수동 정기 실행을 예약했습니다.");
      return true;
    } catch (error) {
      setActionError(operationsWriteError(error, "schedule_execution"));
      await refreshOperationsReads(queryClient, Object.values(operationsQueryKeys));
      return false;
    } finally {
      setExecutionBusy(false);
      executionWriteInFlight.current = false;
    }
  };

  const loading = settingsQuery.isLoading || alwaysOnQuery.isLoading || executionsQuery.isLoading;
  const readError = settingsQuery.error || alwaysOnQuery.error || executionsQuery.error;
  if (loading && (!settingsQuery.data || !alwaysOnQuery.data || !executionsQuery.data)) {
    return <div className="operations-loading" role="status" aria-live="polite">상시 운영 설정과 실행 이력을 불러오는 중입니다.</div>;
  }
  if (readError || !settingsQuery.data || !alwaysOnQuery.data || !executionsQuery.data) {
    return <EmptyState title="상시 운영 정보를 불러오지 못했습니다." description="스케줄 설정·상시 운영·실행 이력 API를 확인하십시오." action={{ label: "다시 시도", onClick: () => { void settingsQuery.refetch(); void alwaysOnQuery.refetch(); void executionsQuery.refetch(); } }} />;
  }

  return (
    <div className="operations-page">
      <header className="operations-page-header">
        <div><span className="operations-eyebrow">운영 · 승인 경계</span><h2>상시 운영</h2><p>일간·주간 정기 실행을 관리하고 현재 승인 조합과 실행 결과를 확인합니다.</p></div>
        <div className="operations-header-summary"><span>시간대</span><strong className="mono">Asia/Seoul</strong><small>기본값 · 상시 운영 꺼짐</small></div>
      </header>
      {actionMessage ? <p className="operations-action-message" role="status" aria-live="polite">{actionMessage}</p> : null}
      {actionError ? <p className="operations-action-error" role="alert">{actionError}</p> : null}
      <div className="operations-layout">
        <div className="operations-main-column">
          <section className="operations-panel operations-settings-panel" aria-labelledby="operations-settings-title">
            <div className="operations-panel-heading"><div><span className="operations-eyebrow">정기 예약</span><h3 id="operations-settings-title">스케줄 설정</h3></div><span className="operations-panel-note">DB 정본</span></div>
            <div className="operations-panel-body"><ScheduleSettingsForm settings={settingsQuery.data} busy={settingsBusy} onSave={saveSettings} /></div>
          </section>
          <AlwaysOnPanel state={alwaysOnQuery.data} activePolicy={activePolicy} activePolicyVersion={activePolicyVersion} policyLoading={policiesQuery.isLoading} policyRefreshing={policiesQuery.isFetching} busy={alwaysOnBusy} onUpdate={updateAlwaysOn} />
          <ScheduleExecutionForm recoveryTarget={recoveryTarget} busy={executionBusy} onSubmit={submitExecution} onCancelRecovery={() => setRecoveryTarget(null)} />
        </div>
        <aside className="operations-side-column" aria-label="승인 조합 요약">
          <section className="operations-panel operations-guard-panel" aria-labelledby="operations-guard-title">
            <div className="operations-panel-heading"><div><span className="operations-eyebrow">운영 전 확인</span><h3 id="operations-guard-title">활성화 조건</h3></div></div>
            <div className="operations-panel-body">
              <ul className="operations-guard-list">
                <li><span aria-hidden="true">01</span><div><strong>환경 허용</strong><small>환경 안전 상한과 DB 스위치가 모두 필요합니다.</small></div></li>
                <li><span aria-hidden="true">02</span><div><strong>운영 승인 게이트</strong><small>최신 evaluation 결과가 통과여야 합니다.</small></div></li>
                <li><span aria-hidden="true">03</span><div><strong>정확한 결과 ID</strong><small>켜기 시 담당자가 quality gate evaluation ID를 확인합니다.</small></div></li>
              </ul>
              <p className="operations-side-note">승인 조합이 바뀌면 신규 예약은 차단되고, 이미 끝난 회차와 산출물은 삭제하거나 수정하지 않습니다.</p>
            </div>
          </section>
          {policiesQuery.error ? <p className="operations-side-warning" role="status">활성 정책 digest를 조회할 수 없습니다. 상시 운영 응답의 정책 버전만 표시합니다.</p> : null}
        </aside>
      </div>
      <ScheduleExecutionTable items={executionsQuery.data.items} onRecover={(item) => { setRecoveryTarget(item); setActionMessage(null); setActionError(null); }} />
    </div>
  );
}
