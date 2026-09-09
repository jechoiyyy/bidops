import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { Button } from "@astryxdesign/core/Button";
import { Text } from "@astryxdesign/core/Text";
import { Settings2 } from "lucide-react";
import { ActivationPaneBody, AlwaysOnActions, computeActivation } from "../components/operations/AlwaysOnPanel";
import { ManualExecutionDialog } from "../components/operations/ManualExecutionDialog";
import { ScheduleExecutionTable } from "../components/operations/ScheduleExecutionTable";
import { ScheduleSettingsDialog } from "../components/operations/ScheduleSettingsDialog";
import { operationsWriteError } from "../components/operations/feedback";
import {
  Caption,
  DetailFooter,
  DetailHeader,
  Facts,
  ListRecord,
  Note,
  Section,
} from "../components/runs/RunStatusPrimitives";
import { api } from "../lib/api";
import type { ScheduleExecutionCreateRequest, ScheduleExecutionSummary } from "../lib/types";

// 상시 운영 탭. 좌: 활성화 조건 · 스케줄 설정 · 예약 실행 이력 세 항목.
// 우: 고른 항목의 실제 값. 스케줄 수정과 수동 실행 예약은 전체 양식을 유지한
// 채 대화상자로 옮겼다. 저장이 상시 운영을 켜지 않는다.

type OperationsPane = "activation" | "schedule" | "history";

const PANES: Array<{ key: OperationsPane; title: string }> = [
  { key: "activation", title: "활성화 조건" },
  { key: "schedule", title: "스케줄 설정" },
  { key: "history", title: "예약 실행 이력" },
];

const operationsQueryKeys = {
  settings: ["operations", "schedule-settings"],
  alwaysOn: ["operations", "always-on"],
  executions: ["operations", "schedule-executions"],
  policies: ["operations", "policies"],
  // 화면 위 요약 한 줄이 읽는 키다. 여기서 쓰기가 일어나면 요약도 같이
  // 최신화해야 상세와 요약이 서로 다른 상태를 말하지 않는다.
  summaryAlwaysOn: ["always-on"],
} as const;

async function refreshOperationsReads(
  queryClient: ReturnType<typeof useQueryClient>,
  queryKeys: readonly (readonly string[])[],
): Promise<void> {
  // 충돌이 나도 거절·비활성·감사 투영은 커밋될 수 있다. 관련 조회를 즉시 다시
  // 읽되, 여기서의 실패가 원래 쓰기 결과를 가리거나 미처리 promise를 남기지
  // 않게 한다.
  await Promise.all(queryKeys.map(async (queryKey) => {
    try {
      await queryClient.invalidateQueries({ queryKey, refetchType: "active" });
    } catch {
      // 다음 안전 폴링 주기가 일시적으로 실패한 조회를 다시 시도한다.
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
        await Promise.all([
          queryClient.invalidateQueries({ queryKey: operationsQueryKeys.settings }),
          queryClient.invalidateQueries({ queryKey: operationsQueryKeys.alwaysOn }),
          queryClient.invalidateQueries({ queryKey: operationsQueryKeys.executions }),
          queryClient.invalidateQueries({ queryKey: operationsQueryKeys.policies }),
          queryClient.invalidateQueries({ queryKey: operationsQueryKeys.summaryAlwaysOn }),
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

export function OperationsPage({ panelId = "run-status-panel-operations" }: { panelId?: string }) {
  const queryClient = useQueryClient();
  const [searchParams, setSearchParams] = useSearchParams();
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
  const [scheduleDialogOpen, setScheduleDialogOpen] = useState(false);
  const [manualDialogOpen, setManualDialogOpen] = useState(false);
  const settingsWriteInFlight = useRef(false);
  const alwaysOnWriteInFlight = useRef(false);
  const executionWriteInFlight = useRef(false);

  const paneParam = searchParams.get("pane");
  const pane: OperationsPane = PANES.some((item) => item.key === paneParam) ? paneParam as OperationsPane : "activation";
  const selectPane = (next: OperationsPane) => {
    setSearchParams((current) => {
      const params = new URLSearchParams(current);
      params.set("pane", next);
      return params;
    }, { replace: true });
  };

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
      setActionMessage("정기 실행 설정을 저장했습니다. 상시 운영 상태는 바뀌지 않았습니다.");
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

  const settings = settingsQuery.data ?? null;
  const alwaysOn = alwaysOnQuery.data ?? null;
  const executions = executionsQuery.data?.items ?? [];
  const loading = settingsQuery.isLoading || alwaysOnQuery.isLoading || executionsQuery.isLoading;
  const activation = alwaysOn
    ? computeActivation(alwaysOn, activePolicy, activePolicyVersion, policiesQuery.isLoading, policiesQuery.isFetching)
    : null;

  const paneItems = PANES.map((item) => {
    if (item.key === "activation") {
      return {
        ...item,
        subtitle: alwaysOnQuery.error
          ? "상시 운영 상태 미확인"
          : alwaysOn
            ? `실제 ${alwaysOn.effective_enabled ? "켜짐" : "꺼짐"} · 환경 ${alwaysOn.environment_enabled ? "허용" : "차단"}`
            : "상태 확인 중",
        meta: alwaysOnQuery.error
          ? "조회 실패는 꺼짐이 아닙니다"
          : activation
            ? activation.blockers.length > 0 ? `미충족 조건 ${activation.blockers.length}건` : "구조 조건 충족"
            : "확인 중",
        status: alwaysOnQuery.error ? "미확인" : alwaysOn ? (alwaysOn.effective_enabled ? "켜짐" : "꺼짐") : "확인 중",
      };
    }
    if (item.key === "schedule") {
      return {
        ...item,
        subtitle: settingsQuery.error
          ? "설정 미확인"
          : settings
            ? `일간 ${settings.daily_time} · 주간 월요일 ${settings.weekly_time}`
            : "설정 확인 중",
        meta: settings ? `기준 시간대 ${settings.timezone} · 사전규격 ${settings.prespec_enabled ? "포함" : "포함하지 않음"}` : "확인 중",
        status: undefined,
      };
    }
    return {
      ...item,
      subtitle: executionsQuery.error ? "이력 미확인" : `최근 ${executions.length}건`,
      meta: executionsQuery.error
        ? "조회 실패는 이력 0건이 아닙니다"
        : `복구 대상 ${executions.filter((execution) => ["실패", "부분 성공", "건너뜀"].includes(execution.status)).length}건`,
      status: undefined,
    };
  });

  const activePaneTitle = PANES.find((item) => item.key === pane)?.title ?? "운영 항목";

  return (
    <div className="rs-workspace" id={panelId} role="tabpanel" aria-label="상시 운영">
      <section className="rs-list-pane" aria-label="운영 항목">
        <header className="rs-list-head">
          <Text className="rs-list-title" as="p">운영 항목</Text>
          <Caption as="span">{PANES.length}건</Caption>
        </header>
        <div className="rs-list-scroll">
          {paneItems.map((item) => (
            <ListRecord
              key={item.key}
              selected={pane === item.key}
              onSelect={() => selectPane(item.key)}
              item={{ id: item.key, title: item.title, subtitle: item.subtitle, meta: item.meta, status: item.status }}
            />
          ))}
        </div>
        <footer className="rs-list-foot">
          <Caption>설정 저장과 운영 활성화는 별도입니다. 수동 실행은 상시 운영과 별개로 요청합니다.</Caption>
        </footer>
      </section>

      <section className="rs-detail-pane" aria-label="선택한 운영 항목">
        <DetailHeader
          eyebrow="상시 운영 · 수집과 판정 예약"
          title={activePaneTitle}
          status={alwaysOnQuery.error ? "미확인" : alwaysOn ? (alwaysOn.effective_enabled ? "켜짐" : "꺼짐") : "확인 중"}
          statusDescription="상시 운영의 실제 상태입니다."
        >
          <Caption>
            {settings ? `기준 시간대 ${settings.timezone}` : "기준 시간대 확인 중"}
            {" · 앱 시작은 migration·seed·정책 활성화·모델 호출을 수행하지 않습니다"}
          </Caption>
        </DetailHeader>

        <div className="rs-detail-scroll">
          {actionMessage ? <Note title={actionMessage} role="status" /> : null}
          {actionError ? <Note title={actionError} tone="error" /> : null}

          {pane === "activation" ? (
            <>
              {alwaysOnQuery.error ? (
                <Note title="상시 운영 상태를 불러오지 못했습니다" tone="error">
                  꺼져 있다는 뜻도 켜져 있다는 뜻도 아닙니다. 현재 상태는 미확인이며 이 화면에서 켜거나 끌 수
                  없습니다.
                </Note>
              ) : null}
              {loading && !alwaysOn ? <Caption>상시 운영 상태를 불러오는 중입니다.</Caption> : null}
              <Caption>
                설정 저장과 운영 활성화는 별도입니다. 수동 실행은 상시 운영이 꺼져 있어도 요청할 수
                있습니다.
              </Caption>
              {alwaysOn && activation ? (
                <ActivationPaneBody
                  state={alwaysOn}
                  view={activation}
                  policyLoading={policiesQuery.isLoading}
                  policyError={Boolean(policiesQuery.error)}
                />
              ) : null}
            </>
          ) : null}

          {pane === "schedule" ? (
            <>
              {settingsQuery.error ? (
                <Note title="스케줄 설정을 불러오지 못했습니다" tone="error">
                  현재 예약 시각은 미확인입니다. 기본값으로 가정하지 않습니다.
                </Note>
              ) : null}
              {loading && !settings ? <Caption>스케줄 설정을 불러오는 중입니다.</Caption> : null}
              {settings ? (
                <>
                  <Section title="현재 예약 설정">
                    <Facts
                      items={[
                        ["일간 실행", `매일 ${settings.daily_time}`],
                        ["주간 실행", `월요일 ${settings.weekly_time}`],
                        ["시간대", <span className="rs-mono" key="tz">{settings.timezone}</span>],
                        ["사전규격 수집", settings.prespec_enabled ? "포함" : "포함하지 않음"],
                        [
                          "다음 실제 실행",
                          alwaysOn
                            ? alwaysOn.effective_enabled ? "예약 시각에 실행" : "상시 운영이 꺼져 있어 예약 실행 없음"
                            : "상시 운영 상태 미확인",
                        ],
                        ["마지막 변경", <span className="rs-mono" key="updated">{settings.updated_at}</span>],
                      ]}
                    />
                  </Section>
                  <Note title="예약 시간을 바꿔도 상시 운영이 켜지지 않습니다">
                    설정 저장과 운영 활성화는 별도 조작입니다. 수정 창의 초안은 저장하기 전까지 현재 값에
                    반영되지 않습니다.
                  </Note>
                </>
              ) : null}
            </>
          ) : null}

          {pane === "history" ? (
            <>
              {executionsQuery.error ? (
                <Note title="정기 실행 이력을 불러오지 못했습니다" tone="error">
                  조회 실패는 실행 0건이 아닙니다.
                </Note>
              ) : null}
              {loading && !executionsQuery.data ? <Caption>정기 실행 이력을 불러오는 중입니다.</Caption> : null}
              {executionsQuery.data ? (
                <ScheduleExecutionTable
                  items={executions}
                  onRecover={(item) => {
                    setRecoveryTarget(item);
                    setActionMessage(null);
                    setActionError(null);
                    setManualDialogOpen(true);
                  }}
                />
              ) : null}
              <Note title="거절된 예약을 실행 성공으로 표시하지 않습니다">
                예약, 실제 실행, 결과 게시를 구분해서 확인합니다. 수동 실행은 상시 운영이 꺼져 있어도
                담당자가 직접 요청할 수 있습니다.
              </Note>
            </>
          ) : null}
        </div>

        <DetailFooter note="설정과 실제 운영은 별도">
          <Button
            label="수동 실행 예약"
            size="sm"
            onClick={() => { setRecoveryTarget(null); setActionError(null); setManualDialogOpen(true); }}
          />
          {pane === "schedule" ? (
            <Button
              label="스케줄 수정"
              size="sm"
              icon={<Settings2 aria-hidden="true" />}
              isDisabled={!settings}
              onClick={() => { setActionError(null); setScheduleDialogOpen(true); }}
            />
          ) : null}
          {pane === "activation" && alwaysOn && activation ? (
            <AlwaysOnActions
              state={alwaysOn}
              view={activation}
              busy={alwaysOnBusy}
              onUpdate={updateAlwaysOn}
              activePolicyVersion={activePolicyVersion}
            />
          ) : null}
        </DetailFooter>
      </section>

      {settings ? (
        <ScheduleSettingsDialog
          open={scheduleDialogOpen}
          onClose={() => setScheduleDialogOpen(false)}
          settings={settings}
          busy={settingsBusy}
          saveError={actionError}
          onSave={saveSettings}
        />
      ) : null}
      <ManualExecutionDialog
        open={manualDialogOpen}
        onClose={() => setManualDialogOpen(false)}
        recoveryTarget={recoveryTarget}
        busy={executionBusy}
        submitError={actionError}
        onSubmit={submitExecution}
        onCancelRecovery={() => setRecoveryTarget(null)}
      />
    </div>
  );
}
