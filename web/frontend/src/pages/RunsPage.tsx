import { AdminListHeader, AdminRecordTable } from "../components/common/AdminRecordTable";
import type { RecordTableState } from "../components/common/RecordTable";
import { DecisionBar, DetailTabs, ReviewFilterSegmentedControl, ReviewPreviewHeader, SplitWorkspace } from "../components/common/ReviewPrimitives";
import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useLocation, useSearchParams } from "react-router-dom";
import { Button } from "@astryxdesign/core/Button";
import { Tab } from "@astryxdesign/core/TabList";
import { Text } from "@astryxdesign/core/Text";
import { TextInput } from "@astryxdesign/core/TextInput";
import { Pause, Play, Search, SlidersHorizontal } from "lucide-react";
import { StatusMark } from "../components/common/Marks";
import { NoticeGradeMark } from "../components/notice/NoticeMarks";
import { ExecutionLog } from "../components/runs/ExecutionLog";
import { FailurePanel, TelemetrySummary } from "../components/runs/FailurePanel";
import { JudgmentStartDialog, JudgmentStopDialog } from "../components/runs/JudgmentDialogs";
import { OrderPlanScreeningPanel } from "../components/runs/OrderPlanScreeningPanel";
import { PipelineControlsDialog } from "../components/runs/PipelineControlsDialog";
import { PipelineStageTrack } from "../components/runs/PipelineStages";
import {
  Caption,
  DataTable,
  DetailHeader,
  Facts,
  Note,
  Section,
} from "../components/runs/RunStatusPrimitives";
import { ScreeningRunPanel, screeningStatusLabel } from "../components/runs/ScreeningRunPanel";
import {
  isScreeningTerminal,
  latestExecutionByRun,
  needsAttention,
  useRecentScreeningExecutions,
  validationMetricBasisLabel,
  validationMetricStatusLabel,
  validationMetricTone,
  executionStatusTone,
  validationMetricValueLabel,
} from "../components/runs/runStatusData";
import { api } from "../lib/api";
import { formatDateTime, formatNumber, formatRunRange, present, runStatusLabel } from "../lib/format";
import type {
  CompanyProfileSnapshotResponse,
  PolicyVersionResponse,
  ProfileSource,
  RunSummary,
  ScreeningExecutionDetailResponse,
  ScreeningExecutionResponse,
} from "../lib/types";

// 수집 실행 탭. 승인된 시안의 목록 38% / 상세 62% 골격을 그대로 쓰고, 상세는
// 진행 현황 · 실패 내역 · 실행 기록 · 실행 기준 네 탭으로 나눈다. 큰 실행 폼과
// 파이프라인 조작은 없애지 않고 바닥 액션의 대화상자로 옮겼다.

type RunnableStage = "collect" | "sample" | "report";
type DetailTab = "summary" | "failures" | "logs" | "binding" | "order_plan_screening";
type ListFilter = "all" | "running" | "issue";

const DETAIL_TABS: Array<{ key: DetailTab; label: string }> = [
  { key: "summary", label: "진행 현황" },
  { key: "failures", label: "실패 내역" },
  { key: "logs", label: "실행 기록" },
  { key: "binding", label: "실행 기준" },
];

/**
 * 발주계획 선별(C-2) 실행 기록의 운영 수신처(spec §4). 발주계획·혼합 회차에만
 * 붙는 다섯째 탭이며 공고 회차에서는 지금까지와 같은 네 탭이다.
 */
const ORDER_PLAN_SCREENING_TAB: { key: DetailTab; label: string } = {
  key: "order_plan_screening",
  label: "발주계획 선별",
};

/** 발주계획이 들어 있는 회차. 혼합 회차도 발주계획 선별 실행을 가질 수 있다. */
function hasOrderPlans(kind: string): boolean {
  return kind === "order_plans" || kind === "mixed";
}

/** 사전규격은 공고 수집에서 나온다. 혼합 회차는 둘 다 가리킬 수 있다. */
function hasNotices(kind: string): boolean {
  return kind === "notices" || kind === "mixed";
}

const RUN_KIND_LABELS: Record<string, string> = {
  order_plans: "발주계획 회차",
  notices: "공고 판정 회차",
  mixed: "혼합 회차",
  unknown: "회차 종류 미확인",
};

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "수집 실행을 시작하지 못했어요.";
}

function countFromCollection(run: RunSummary, key: string): number | null {
  const value = run.counts.collection[key];
  return typeof value === "number" ? value : null;
}

function profileSourceFor(snapshot: CompanyProfileSnapshotResponse): ProfileSource | null {
  if (snapshot.source_kind === "working_tree") return "current";
  return snapshot.source_ref ? `git:${snapshot.source_ref}` : null;
}

/** 서버 오류 본문을 화면에 옮기지 않는다(docs/security.md). */
function screeningActionMessage(): string {
  return "판정 실행 요청을 처리하지 못했어요. 입력과 실행 상태를 확인한 뒤 다시 시도해 주세요.";
}

/**
 * 선택한 실행 하나만 상세를 조회한다. 목록의 모든 행을 상세로 조회하지 않는다.
 * 중단 신호는 늦게 도착한 응답이 이미 바뀐 화면을 덮는 것을 막는다.
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
        // 상세 조회 실패는 일시적으로 두고 계속 시도한다. 서버 오류 본문을
        // 상태로 승격시키지 않는다.
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

export function RunsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const { key: locationKey } = useLocation();
  const queryClient = useQueryClient();

  const runsQuery = useQuery({ queryKey: ["runs"], queryFn: api.getRuns, staleTime: 5_000 });
  const runs = useMemo(() => runsQuery.data?.items ?? [], [runsQuery.data]);
  const queryRunId = searchParams.get("run");
  const selectedRunId = runs.some((run) => run.run_id === queryRunId) ? queryRunId : runs[0]?.run_id ?? null;
  /**
   * `발주계획 선별` 탭이 고른 C-2 실행. 회차 하나에 실행이 여럿일 수 있으므로
   * 선택을 주소에 남긴다. 이 회차의 실행이 아니면 패널이 무시하고 가장 최근
   * 실행을 고른다 — 조용히 다른 회차의 실행을 보여주지 않는다.
   */
  const orderPlanExecutionId = searchParams.get("execution")?.trim() || null;
  const requestedOrderPlanView = searchParams.get("view") === "order-plan-screening";

  const detailQuery = useQuery({
    queryKey: ["run", selectedRunId],
    queryFn: () => api.getRun(selectedRunId as string),
    enabled: Boolean(selectedRunId),
    staleTime: 2_000,
  });
  const orderPlansOnly = detailQuery.data?.kind === "order_plans";
  const loadNoticeMetrics = Boolean(detailQuery.data) && !orderPlansOnly;
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
  // 대시보드 `회차 요약`·`검증 상태`의 이식(ADR-0066 결정 7). 두 패널이 읽던
  // 회차 통계·검증 지표를 이 회차 상세가 직접 조회한다.
  const runStatsQuery = useQuery({
    queryKey: ["run-stats", selectedRunId],
    queryFn: () => api.getRunStats(selectedRunId as string),
    enabled: loadNoticeMetrics,
    staleTime: 30_000,
  });
  const validationQuery = useQuery({
    queryKey: ["validation-metrics", selectedRunId],
    queryFn: () => api.getValidationMetrics(selectedRunId as string),
    enabled: loadNoticeMetrics,
    staleTime: 30_000,
  });

  const [detailTab, setDetailTab] = useState<DetailTab>("summary");
  const [listQuery, setListQuery] = useState("");
  const [listFilter, setListFilter] = useState<ListFilter>("all");
  const [startDialogOpen, setStartDialogOpen] = useState(false);
  const [stopDialogOpen, setStopDialogOpen] = useState(false);
  const [pipelineDialogOpen, setPipelineDialogOpen] = useState(false);
  const [stopTarget, setStopTarget] = useState<ScreeningExecutionResponse | null>(null);

  // 정책·프로필은 실행 요청 창을 열 때만 조회한다. 기본 화면이 쓰지 않는다.
  const activationCandidatePoliciesQuery = useQuery({
    queryKey: ["screening-policies", "activation_candidate"],
    queryFn: () => api.getPolicies({ status: "activation_candidate" }),
    enabled: startDialogOpen,
    staleTime: 30_000,
  });
  const activePoliciesQuery = useQuery({
    queryKey: ["screening-policies", "active"],
    queryFn: () => api.getPolicies({ status: "active" }),
    enabled: startDialogOpen,
    staleTime: 30_000,
  });
  const profileSnapshotsQuery = useQuery({
    queryKey: ["profile-snapshots"],
    queryFn: api.getProfileSnapshots,
    enabled: startDialogOpen,
    staleTime: 30_000,
  });

  // 선택한 회차의 판정 실행 목록. 회차마다 조회하지 않고 고른 회차 하나만
  // 상한을 두고 받는다.
  const screeningExecutionsQuery = useQuery({
    queryKey: ["screening-executions", selectedRunId],
    queryFn: ({ signal }) => api.listScreeningExecutions(
      { run_id: selectedRunId as string, trigger: "manual_run", limit: 25, offset: 0 },
      { signal },
    ),
    enabled: loadNoticeMetrics,
    staleTime: 0,
    refetchInterval: (query) => {
      const data = query.state.data;
      if (!data) return 1500;
      return data.items.some((execution) => execution.trigger === "manual_run" && execution.scope === "full_run" && !isScreeningTerminal(execution.status)) ? 1500 : false;
    },
  });

  // 목록 행의 판정 실행 상태는 요약 한 줄과 같은 조회를 읽는다. 회차마다
  // 실행을 따로 조회하면 N+1이 된다.
  const recentExecutionsQuery = useRecentScreeningExecutions();
  const executionByRun = useMemo(
    () => latestExecutionByRun(recentExecutionsQuery.data?.items ?? []),
    [recentExecutionsQuery.data],
  );
  const executionScopeKnown = Boolean(recentExecutionsQuery.data) && !recentExecutionsQuery.error;

  const [actionError, setActionError] = useState<string | null>(null);
  const [activeExecutionId, setActiveExecutionId] = useState<string | null>(null);
  const [screeningActor, setScreeningActor] = useState("");
  const [stopActor, setStopActor] = useState("");
  const [selectedPolicyVersion, setSelectedPolicyVersion] = useState("");
  const [selectedProfileVersion, setSelectedProfileVersion] = useState("");
  const [screeningExecutionId, setScreeningExecutionId] = useState<string | null>(null);
  const [screeningActionError, setScreeningActionError] = useState<string | null>(null);
  const [stopActionError, setStopActionError] = useState<string | null>(null);
  const [screeningStartBusy, setScreeningStartBusy] = useState(false);
  const [screeningStopBusy, setScreeningStopBusy] = useState(false);
  const [publishedRunNavigationBusy, setPublishedRunNavigationBusy] = useState(false);
  const [publishedRunNavigationError, setPublishedRunNavigationError] = useState<string | null>(null);
  const screeningStartInFlight = useRef(false);
  const screeningStopInFlight = useRef(false);
  const screeningStartOperation = useRef(0);
  const screeningStopOperation = useRef(0);
  const publishedRunNavigationInFlight = useRef(false);
  const publishedRunNavigationOperation = useRef(0);
  const mountedRef = useRef(true);
  /** `발주계획 선별` 탭을 주소의 `execution`으로 한 번 열어 준 회차. */
  const orderPlanTabOpenedFor = useRef<string | null>(null);
  const selectedScreeningRunRef = useRef<string | null>(selectedRunId);
  const selectedScreeningExecutionRef = useRef<string | null>(screeningExecutionId);
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
  const currentScreeningExecution = screeningDetailPoll.data?.execution_id === screeningExecutionId
    ? screeningDetailPoll.data
    : selectedScreeningSummary;
  const effectiveScreeningExecutionId = screeningExecutionId ?? currentScreeningExecution?.execution_id ?? null;
  if (selectedScreeningExecutionRef.current !== effectiveScreeningExecutionId) {
    selectedScreeningExecutionRef.current = effectiveScreeningExecutionId;
  }
  const currentScreeningExecutionRef = useRef<ScreeningExecutionResponse | null>(currentScreeningExecution);
  currentScreeningExecutionRef.current = currentScreeningExecution;
  const selectedPolicy = policies.find((policy) => policy.policy_version === selectedPolicyVersion) ?? null;
  const selectedProfile = profileSnapshots.find((snapshot) => snapshot.version === selectedProfileVersion) ?? null;
  const screeningDetail = screeningDetailPoll.data?.execution_id === screeningExecutionId ? screeningDetailPoll.data : null;

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
    // 서버는 queue_no 내림차순으로 준다. 진행 중인 실행이 있으면 그것을,
    // 없으면 가장 최근 실행을 고른다. 사람이 고른 실행은 덮지 않는다.
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
    // 회차를 바꾸면 이전 회차의 실행·오류를 새 회차로 들고 오지 않는다.
    screeningStartOperation.current += 1;
    screeningStopOperation.current += 1;
    publishedRunNavigationOperation.current += 1;
    screeningStartInFlight.current = false;
    screeningStopInFlight.current = false;
    publishedRunNavigationInFlight.current = false;
    setScreeningStartBusy(false);
    setScreeningStopBusy(false);
    setPublishedRunNavigationBusy(false);
    setPublishedRunNavigationError(null);
    setScreeningExecutionId(null);
    setScreeningActionError(null);
    setStopActionError(null);
    setStopDialogOpen(false);
    setStopTarget(null);
    setDetailTab("summary");
  }, [selectedRunId]);

  /**
   * 해당 회차의 선별 보기 또는 실행을 가리키는 링크는 발주계획 선별 탭에서 시작한다.
   *
   * 회차 종류는 회차 상세를 받은 뒤에야 알 수 있으므로 초기 상태가 아니라 효과에서
   * 한 번만 옮긴다. 직접 누른 링크는 탐색마다, 실행을 고른 주소는 회차마다 한 번이다.
   */
  useEffect(() => {
    if ((!orderPlanExecutionId && !requestedOrderPlanView) || !selectedRunId || selectedRunId !== queryRunId) return;
    const kind = detailQuery.data?.kind;
    if (!kind || !hasOrderPlans(kind)) return;
    const entry = requestedOrderPlanView ? locationKey : selectedRunId;
    if (orderPlanTabOpenedFor.current === entry) return;
    orderPlanTabOpenedFor.current = entry;
    setDetailTab("order_plan_screening");
  }, [detailQuery.data, locationKey, orderPlanExecutionId, queryRunId, requestedOrderPlanView, selectedRunId]);

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
      // 고른 C-2 실행은 회차에 묶인다. 회차를 바꾸면 주소에서도 지운다.
      next.delete("execution");
      next.delete("view");
      return next;
    }, { replace: true });
  };

  const selectOrderPlanExecution = (executionId: string) => {
    setSearchParams((current) => {
      const next = new URLSearchParams(current);
      next.set("execution", executionId);
      return next;
    }, { replace: true });
  };

  const pipelineBusy = Boolean(logsQuery.data?.executions.some((item) => item.status === "pending" || item.status === "running"));

  const startStage = async (stage: RunnableStage, fromRaw = false) => {
    if (!selectedRunId) return;
    setActionError(null);
    try {
      const execution = await api.runPipeline(selectedRunId, stage, fromRaw);
      setActiveExecutionId(execution.execution_id);
      await queryClient.invalidateQueries({ queryKey: ["pipeline-logs", selectedRunId] });
      setPipelineDialogOpen(false);
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
      setScreeningActionError("현재 회차의 판정 실행 목록을 확인하는 중이에요. 목록을 불러온 뒤 다시 시도해 주세요.");
      return;
    }
    const selectedProfileSource = selectedProfile ? profileSourceFor(selectedProfile) : null;
    if (!capturedRunId || !screeningActor.trim() || !selectedPolicy || !selectedProfile || !selectedProfileSource || hasNonterminalManualFullRun) {
      if (hasNonterminalManualFullRun) setScreeningActionError("이미 진행 중인 전량 판정 실행이 있어요.");
      else setScreeningActionError("담당자 이름, 판정 정책, 프로필 사본을 모두 선택해야 해요.");
      return;
    }
    screeningStartInFlight.current = true;
    const operationToken = ++screeningStartOperation.current;
    setScreeningActionError(null);
    setScreeningStartBusy(true);
    try {
      const execution = await api.enqueueJudgment(capturedRunId, {
        policy_version: selectedPolicy.policy_version,
        profile_source: selectedProfileSource,
        requested_by: screeningActor.trim(),
      });
      const responseIsCurrent = mountedRef.current
        && selectedScreeningRunRef.current === capturedRunId
        && screeningRunGeneration.current === capturedGeneration
        && screeningStartOperation.current === operationToken
        && execution.source_run_id === capturedRunId;
      if (!responseIsCurrent) return;
      setScreeningExecutionId(execution.execution_id);
      setStartDialogOpen(false);
      void queryClient.invalidateQueries({ queryKey: ["screening-executions", capturedRunId] });
      void queryClient.invalidateQueries({ queryKey: ["screening-executions", "recent"] });
    } catch {
      if (mountedRef.current && selectedScreeningRunRef.current === capturedRunId && screeningRunGeneration.current === capturedGeneration) {
        // 충돌·거절이면 창을 닫지 않고 입력을 남겨 다시 시도할 수 있게 한다.
        setScreeningActionError(screeningActionMessage());
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
    // 확인 창이 열릴 때 고정한 대상만 중지한다.
    const capturedExecutionId = stopTarget?.execution_id ?? null;
    const latestStatus = screeningDetailPoll.data?.execution_id === capturedExecutionId
      ? screeningDetailPoll.data.status
      : manualFullRunExecutions.find((item) => item.execution_id === capturedExecutionId)?.status;
    if (screeningStopInFlight.current) return;
    if (!capturedRunId || !capturedExecutionId || !stopActor.trim() || !latestStatus || isScreeningTerminal(latestStatus) || latestStatus === "중지 요청") {
      setStopActionError("이 실행은 더 이상 중지할 수 없어요. 상태를 다시 확인해 주세요.");
      return;
    }
    screeningStopInFlight.current = true;
    const operationToken = ++screeningStopOperation.current;
    setStopActionError(null);
    setScreeningStopBusy(true);
    try {
      const stopped = await api.stopScreeningExecution(capturedExecutionId, { requested_by: stopActor.trim() });
      const responseIsCurrent = mountedRef.current
        && selectedScreeningRunRef.current === capturedRunId
        && screeningRunGeneration.current === capturedGeneration
        && screeningStopOperation.current === operationToken
        && stopped.source_run_id === capturedRunId;
      if (!responseIsCurrent) return;
      setScreeningExecutionId(stopped.execution_id);
      setStopDialogOpen(false);
      setStopTarget(null);
      void queryClient.invalidateQueries({ queryKey: ["screening-executions", capturedRunId] });
      void queryClient.invalidateQueries({ queryKey: ["screening-executions", "recent"] });
    } catch {
      if (mountedRef.current && selectedScreeningRunRef.current === capturedRunId && screeningRunGeneration.current === capturedGeneration) {
        setStopActionError(screeningActionMessage());
      }
    } finally {
      if (mountedRef.current && screeningStopOperation.current === operationToken) {
        setScreeningStopBusy(false);
        screeningStopInFlight.current = false;
      }
    }
  };

  const selectPublishedRun = async (publishedRunId: string) => {
    const capturedRunId = selectedRunId;
    const capturedGeneration = screeningRunGeneration.current;
    const capturedExecutionId = selectedScreeningExecutionRef.current;
    const selectedExecution = currentScreeningExecutionRef.current?.execution_id === capturedExecutionId
      ? currentScreeningExecutionRef.current
      : null;
    if (
      publishedRunNavigationInFlight.current
      || !capturedRunId
      || !capturedExecutionId
      || !publishedRunId.trim()
      || !selectedExecution
      || selectedExecution.source_run_id !== capturedRunId
      || selectedExecution.published_run_id !== publishedRunId
    ) return;

    publishedRunNavigationInFlight.current = true;
    const operationToken = ++publishedRunNavigationOperation.current;
    setPublishedRunNavigationBusy(true);
    setPublishedRunNavigationError(null);
    const isCurrent = () => mountedRef.current
      && publishedRunNavigationOperation.current === operationToken
      && selectedScreeningRunRef.current === capturedRunId
      && screeningRunGeneration.current === capturedGeneration
      && selectedScreeningExecutionRef.current === capturedExecutionId;
    try {
      const refreshed = await runsQuery.refetch();
      if (!isCurrent()) return;
      if (refreshed.error || !refreshed.data) {
        setPublishedRunNavigationError("파생 회차 목록을 확인하지 못했어요. 다시 시도해 주세요.");
        return;
      }
      const targetExists = refreshed.data?.items.some((run) => run.run_id === publishedRunId) ?? false;
      if (!targetExists) {
        setPublishedRunNavigationError("게시된 파생 회차가 아직 회차 목록에 없어요. 잠시 후 다시 시도해 주세요.");
        return;
      }
      const currentExecution = currentScreeningExecutionRef.current?.execution_id === capturedExecutionId
        ? currentScreeningExecutionRef.current
        : null;
      if (!currentExecution || currentExecution.source_run_id !== capturedRunId || currentExecution.published_run_id !== publishedRunId) return;
      setSearchParams((current) => {
        const next = new URLSearchParams(current);
        next.set("run", publishedRunId);
        return next;
      }, { replace: false });
    } catch {
      if (isCurrent()) setPublishedRunNavigationError("파생 회차 목록을 확인하지 못했어요. 다시 시도해 주세요.");
    } finally {
      if (mountedRef.current && publishedRunNavigationOperation.current === operationToken) {
        setPublishedRunNavigationBusy(false);
        publishedRunNavigationInFlight.current = false;
      }
    }
  };

  // ── 목록 좁히기 ─────────────────────────────────────────────────────────
  const term = listQuery.trim();
  const matchesFilter = (run: RunSummary): boolean => {
    if (listFilter === "all") return true;
    const execution = executionByRun.get(run.run_id);
    if (!execution) return false;
    if (listFilter === "running") return !isScreeningTerminal(execution.status);
    return needsAttention(execution.status);
  };
  const visibleRuns = runs.filter((run) => matchesFilter(run)
    && (term === "" || `${run.run_id} ${formatRunRange(run.run_id, run.window_from, run.window_to)} ${run.kind}`.includes(term)));
  const runningCount = runs.filter((run) => {
    const execution = executionByRun.get(run.run_id);
    return execution ? !isScreeningTerminal(execution.status) : false;
  }).length;
  const attentionCount = runs.filter((run) => {
    const execution = executionByRun.get(run.run_id);
    return execution ? needsAttention(execution.status) : false;
  }).length;

  const detail = detailQuery.data ?? null;
  const selectedSummary = runs.find((run) => run.run_id === selectedRunId) ?? detail;
  const detailTabs = orderPlansOnly
    ? [ORDER_PLAN_SCREENING_TAB, DETAIL_TABS[2]]
    : detail && hasOrderPlans(detail.kind)
    ? [...DETAIL_TABS, ORDER_PLAN_SCREENING_TAB]
    : DETAIL_TABS;
  const visibleTab = orderPlansOnly && detailTab !== "logs" ? "order_plan_screening" : detailTab;
  const currentStatus = currentScreeningExecution?.status;
  const executionBusy = manualFullRunExecutions.some((item) => !isScreeningTerminal(item.status));
  const screeningListReady = screeningExecutionsQuery.data !== undefined && !screeningExecutionsQuery.isLoading && !screeningExecutionsQuery.error;
  const startDisabled = screeningStartBusy || executionBusy || !screeningListReady || !selectedRunId;
  const startBlockedReason = !screeningListReady
    ? "현재 회차의 판정 실행 목록을 확인할 때까지 실행할 수 없어요."
    : executionBusy
      ? "진행 중인 전량 판정 실행이 있어 새 실행을 시작할 수 없어요."
      : null;
  const canStop = Boolean(currentScreeningExecution)
    && !isScreeningTerminal(currentStatus)
    && currentStatus !== "중지 요청"
    && !screeningStopBusy;

  const screeningState = {
    label: detail?.kind === "order_plans" ? "발주계획 선별" : currentScreeningExecution
      ? screeningStatusLabel(currentStatus)
      : screeningListReady ? "판정 실행 없음" : "판정 실행 미확인",
    tone: executionStatusTone(detail?.kind === "order_plans" ? null : currentStatus),
  };

  function listExecutionSummary(run: RunSummary): string {
    if (run.kind === "order_plans") return "선별 결과는 발주계획 선별 탭에서 확인";
    const execution = executionByRun.get(run.run_id);
    return `공고 판정 실행 ${executionScopeKnown ? (execution ? screeningStatusLabel(execution.status) : "조회 범위 안 기록 없음") : "미확인"}`;
  }

  const listFooter = `받은 회차 ${runs.length.toLocaleString("ko-KR")}건 · 표시 ${visibleRuns.length.toLocaleString("ko-KR")}건`
    + (executionScopeKnown
      ? ` · 판정 실행 상태는 최근 ${(recentExecutionsQuery.data?.items.length ?? 0).toLocaleString("ko-KR")}건 조회 범위 기준이며 범위 밖은 미확인이에요`
      : " · 판정 실행 상태는 미확인이에요");

  let listState: RecordTableState | undefined;
  if (runsQuery.isPending) {
    listState = { kind: "loading", label: "실행 회차를 불러오는 중이에요.", showLabel: true };
  } else if (runsQuery.error) {
    listState = { kind: "error", message: {
      title: "실행 회차를 불러오지 못했어요.",
      description: "조회 실패는 회차 0건이 아니에요.",
      action: { label: "다시 시도", onClick: () => { void runsQuery.refetch(); } },
    } };
  } else if (runs.length === 0) {
    listState = { kind: "empty", message: {
      title: "적재된 실행 회차가 없어요.",
      description: "회차가 적재되면 이곳에서 파이프라인과 판정 실행을 확인할 수 있어요.",
    } };
  } else if (visibleRuns.length === 0) {
    listState = { kind: "empty", message: {
      title: "조건에 맞는 회차가 없어요.",
      description: "받은 목록 안에 없을 뿐, 전체에 없다는 뜻은 아니에요.",
      action: { label: "필터 초기화", onClick: () => { setListQuery(""); setListFilter("all"); } },
    } };
  }
  return (
    <SplitWorkspace className="workbench-admin-workspace" aria-label="수집 실행">
      <section className="review-split-list" aria-label="실행 회차 목록">
        <AdminListHeader
          title="실행 회차 목록"
          count={runsQuery.isError ? "미확인" : `${runs.length.toLocaleString("ko-KR")}건`}
        >
          <ReviewFilterSegmentedControl
            label="회차 보기"
            layout="hug"
            value={listFilter}
            onChange={(value) => setListFilter(value as ListFilter)}
            options={[
              { value: "all", label: `전체 ${runs.length}` },
              { value: "running", label: executionScopeKnown ? `실행 중 ${runningCount}` : "실행 중 미확인" },
              { value: "issue", label: executionScopeKnown ? `확인 필요 ${attentionCount}` : "확인 필요 미확인" },
            ]}
          />
          <TextInput
            label="실행 회차 검색"
            isLabelHidden
            placeholder="회차·기간 검색"
            value={listQuery}
            onChange={setListQuery}
            startIcon={Search}
            hasClear
            size="sm"
          />
        </AdminListHeader>
        <AdminRecordTable
          label="실행 회차 목록"
          identifierWidth={186}
          selectedId={selectedRunId}
          onSelect={selectRun}
          state={listState}
          rows={visibleRuns.map((run) => {
            const execution = executionByRun.get(run.run_id);
            const orderPlansOnly = run.kind === "order_plans";
            return {
              title: RUN_KIND_LABELS[run.kind] ?? "회차 종류 미확인",
              id: run.run_id,
              subtitle: formatRunRange(run.run_id, run.window_from, run.window_to),
              meta: `${formatDateTime(run.generated_at)} · 수집 ${formatNumber(countFromCollection(run, "total"))} · 회차 ${runStatusLabel(run.status)} · ${listExecutionSummary(run)}`,
              status: {
                label: orderPlansOnly ? "발주계획 선별"
                  : execution ? screeningStatusLabel(execution.status) : executionScopeKnown ? "판정 실행 없음" : "판정 실행 미확인",
                tone: executionStatusTone(orderPlansOnly ? null : execution?.status),
              },
              statusDescription: orderPlansOnly
                ? "이 회차의 실행 결과는 발주계획 선별 탭에 있어요."
                : "이 회차에 연결된 공고 판정 실행의 상태예요.",
            };
          })}
        />
        <footer className="workbench-admin-list-foot">
          <Caption>{listFooter}</Caption>
        </footer>
      </section>

      <section className="review-split-detail rs-detail-pane" aria-label="선택한 실행 회차">
        <ReviewPreviewHeader />
        {detailQuery.isError ? (
          <div className="rs-detail-empty" role="alert">
            <Text as="p">회차 상세를 불러오지 못했어요.</Text>
            <Caption>조회 실패를 실행 없음으로 읽지 않아요.</Caption>
            <Button label="다시 시도" size="sm" onClick={() => void detailQuery.refetch()} />
          </div>
        ) : null}
        {!detailQuery.isError && (!detail || !selectedSummary) ? (
          <div className="rs-detail-empty">
            <Text as="p">{selectedRunId ? "선택한 회차의 상세 정보를 불러오는 중이에요." : "확인할 실행 회차를 골라 주세요."}</Text>
          </div>
        ) : null}
        {!detailQuery.isError && detail && selectedSummary ? (
          <>
            <DetailHeader
              eyebrow={`선택한 회차 · ${formatRunRange(detail.run_id, detail.window_from, detail.window_to)}`}
              title={RUN_KIND_LABELS[detail.kind] ?? "회차 종류 미확인"}
              // 머리의 주 상태는 **지금 고른 판정 실행**의 상태다. 수집 회차가
              // 끝났다는 사실을 초록 완료로 크게 걸어 두면 진행 중인 판정을
              // 끝난 것으로 읽는다(시안도 실행 상태를 건다).
              status={screeningState}
              statusDescription={detail.kind === "order_plans"
                ? "이 회차의 실행 결과는 발주계획 선별 탭에 있어요."
                : "이 회차에 연결된 공고 판정 실행의 상태예요."}
            >
              <div className="rs-row rs-spread">
                <Caption as="span">
                  <span className="rs-mono">{detail.run_id}</span> · 생성 {formatDateTime(detail.generated_at)}
                  {" · 수집 회차 "}{runStatusLabel(detail.status)}
                </Caption>
                {/* 이 API(ScreeningExecutionResponse·RunSummary)에는 quality_status가
                  * 없다. 측정 통과·참조 실행·mock 참조 중 무엇도 주장하지 않고
                  * 표식이 제공되지 않는다는 사실만 중립으로 적는다. */}
                <StatusMark
                  mark={{ label: "품질 표식 미제공", tone: "neutral" }}
                  description="이 실행 API는 품질 표식을 제공하지 않아 측정 통과·참조 실행·mock 참조 여부를 확인할 수 없어요."
                />
              </div>
            </DetailHeader>

            <DetailTabs
              aria-label="선택한 회차 상세 보기"
              onChange={(value) => setDetailTab(value as DetailTab)}
              value={visibleTab}
            >
              {detailTabs.map((item) => (
                <Tab
                  key={item.key}
                  id={`run-tab-${item.key}`}
                  label={item.key === "failures"
                    ? `${item.label} ${currentScreeningExecution ? currentScreeningExecution.failure_count.toLocaleString("ko-KR") : "미확인"}`
                    : item.label}
                  panelId={`run-panel-${item.key}`}
                  value={item.key}
                />
              ))}
            </DetailTabs>

            {detailTabs.filter(({ key }) => key !== visibleTab).map(({ key }) => (
              <div key={key} id={`run-panel-${key}`} role="tabpanel" aria-labelledby={`run-tab-${key}`} hidden />
            ))}
            <div
              aria-labelledby={`run-tab-${visibleTab}`}
              className="workbench-admin-detail-scroll rs-detail-scroll"
              id={`run-panel-${visibleTab}`}
              role="tabpanel"
              tabIndex={0}
            >
              {visibleTab === "summary" ? (
                <>
                  <PipelineStageTrack stages={detail.pipeline} counts={selectedSummary.counts} />
                  {actionError ? (
                    <div className="rs-inline-error" role="alert"><Text as="span">{actionError}</Text></div>
                  ) : null}
                  {/* 단계 → 진행률 → 핵심 건수가 첫 화면에 오도록 안내 문구는
                    * 건수 아래로 내린다. 문구를 지우지 않고 자리만 옮긴다. */}
                  <ScreeningRunPanel
                    blockedReason={startBlockedReason}
                    listRefreshWarning={runsQuery.error ? "회차 목록을 최신화하지 못해 기존 목록을 유지하고 있어요." : null}
                    runId={detail.run_id}
                    executions={manualFullRunExecutions}
                    selectedExecutionId={screeningExecutionId}
                    onSelectExecution={(executionId) => setScreeningExecutionId(executionId)}
                    execution={screeningDetail}
                    executionSummary={selectedScreeningSummary}
                    executionLoading={screeningDetailPoll.loading}
                    executionError={screeningDetailPoll.error}
                    listLoading={screeningExecutionsQuery.isLoading}
                    listError={screeningExecutionsQuery.error}
                    listReady={screeningExecutionsQuery.data !== undefined}
                    listRefreshing={screeningExecutionsQuery.isFetching}
                    onRetryList={() => { void screeningExecutionsQuery.refetch(); }}
                    onOpenPublishedRun={(runId) => void selectPublishedRun(runId)}
                    publishedRunNavigationBusy={publishedRunNavigationBusy}
                    publishedRunNavigationError={publishedRunNavigationError}
                  />
                  <Section title="수집 범위">
                    <Facts
                      items={[
                        ["수집", `${formatNumber(countFromCollection(selectedSummary, "total"))}건`],
                        ["목록의 실행 기록", listExecutionSummary(selectedSummary)],
                        ["판정 후보", `${formatNumber(countFromCollection(selectedSummary, "candidate_pool"))}건`],
                        ["감사 층", `${formatNumber(countFromCollection(selectedSummary, "audit_pool"))}건`],
                        ["표본", `${formatNumber(selectedSummary.counts.notices)}건`],
                        ["적재된 판정", `${formatNumber(selectedSummary.counts.judgments)}건`],
                        ["담당자 리뷰", `${formatNumber(selectedSummary.counts.reviews)}건`],
                      ]}
                    />
                    <Caption>
                      수집·정규화 건수와 판정 후보·시도 건수는 다른 값이에요. 두 건수를 합치거나 서로
                      대신하지 않아요.
                    </Caption>
                  </Section>

                  {/* 대시보드 `회차 요약`의 등급 분포(ADR-0066 결정 7). 건수 4칸은 위
                    * `수집 범위`가 이미 보이므로 되풀이하지 않고 분포만 더한다. */}
                  <Section title="적합성 등급 분포">
                    {runStatsQuery.isError ? (
                      <div className="rs-inline-error" role="alert">
                        <Text as="span">등급 분포를 불러오지 못했어요.</Text>
                        <Button label="다시 조회" size="sm" onClick={() => void runStatsQuery.refetch()} />
                      </div>
                    ) : runStatsQuery.isPending ? (
                      <Caption>등급 분포를 불러오는 중이에요.</Caption>
                    ) : runStatsQuery.data && runStatsQuery.data.grade_distribution.length > 0 ? (
                      <DataTable
                        caption="적합성 등급 분포"
                        headings={["등급", "건수"]}
                        rows={runStatsQuery.data.grade_distribution.map((item) => ({
                          id: item.key,
                          cells: [
                            <NoticeGradeMark key="grade" grade={item.key} label={item.label || item.key} />,
                            // 판정 대기열(`/queue`)로 가는 링크는 2026-11-19에 내렸다 — C-1 공고 판정을
                            // 다시 돌리지 않는다(사전규격 단계 수정안 §3 B). 건수는 그대로 적는다.
                            <span key="count">{formatNumber(item.count)}건</span>,
                          ],
                        }))}
                      />
                    ) : (
                      <Caption>판정 분포 없음</Caption>
                    )}
                  </Section>

                  {/* 대시보드 `검증 상태`의 이식(ADR-0066 결정 7). `계산 불가`·`미확인`을
                    * 0으로 바꾸지 않는다(standards.md "데이터 불변성과 상태"). */}
                  <Section
                    title="검증 지표"
                    action={
                      <Link className="rs-inline-link" to={`/metrics?run=${encodeURIComponent(detail.run_id)}`}>
                        판정 기준 · 검증 지표 →
                      </Link>
                    }
                  >
                    <Facts
                      items={[
                        [
                          "1차 필터 누락",
                          <div className="rs-cell-stack" key="audit-missed">
                            <Text weight="semibold">
                              {runStatsQuery.isPending
                                ? "확인 중"
                                : runStatsQuery.isError
                                  ? "미확인"
                                  : `${formatNumber(runStatsQuery.data?.audit_missed_count)}건`}
                            </Text>
                            <Caption>감사 표본 분모 미확인 · 누락률 계산 불가</Caption>
                          </div>,
                        ],
                      ]}
                    />
                    {validationQuery.isError ? (
                      <div className="rs-inline-error" role="alert">
                        <Text as="span">검증 지표를 불러오지 못했어요.</Text>
                        <Button label="검증 지표 다시 조회" size="sm" onClick={() => void validationQuery.refetch()} />
                      </div>
                    ) : validationQuery.isPending ? (
                      <Caption>검증 지표를 불러오는 중이에요.</Caption>
                    ) : (validationQuery.data?.metrics.length ?? 0) > 0 ? (
                      <DataTable
                        caption="검증 지표"
                        headings={["지표", "결과"]}
                        rows={(validationQuery.data?.metrics ?? []).map((item) => {
                          const value = validationMetricValueLabel(item);
                          const status = validationMetricStatusLabel(item);
                          return {
                            id: item.key,
                            cells: [
                              <div className="rs-cell-stack" key="label">
                                <Text weight="semibold">{item.label || item.key}</Text>
                                <Caption>{validationMetricBasisLabel(item)}</Caption>
                              </div>,
                              <div className="rs-cell-stack rs-align-end" key="result">
                                {value !== status ? <Text weight="semibold">{value}</Text> : null}
                                <StatusMark mark={{ label: status, tone: validationMetricTone(item.status) }} />
                              </div>,
                            ],
                          };
                        })}
                      />
                    ) : (
                      <Caption>검증 지표 없음</Caption>
                    )}
                  </Section>
                </>
              ) : null}

              {visibleTab === "failures" ? (
                <FailurePanel
                  detail={screeningDetail}
                  summary={selectedScreeningSummary}
                  loading={screeningDetailPoll.loading}
                />
              ) : null}

              {visibleTab === "logs" ? (
                <>
                  {orderPlansOnly && <>
                    <PipelineStageTrack stages={detail.pipeline} counts={selectedSummary.counts} />
                    {actionError && <div className="rs-inline-error" role="alert">{actionError}</div>}
                    <Button label="파이프라인 실행" size="sm" onClick={() => { setActionError(null); setPipelineDialogOpen(true); }} />
                  </>}
                  <ExecutionLog data={logsQuery.data} loading={logsQuery.isLoading} error={logsQuery.error} />
                  {!orderPlansOnly && <TelemetrySummary detail={screeningDetail} />}
                </>
              ) : null}

              {visibleTab === "binding" ? (
                <>
                  <Section title="이 실행에 고정된 기준">
                    {currentScreeningExecution ? (
                      <Facts
                        items={[
                          ["실행 ID", <span className="rs-mono" key="exec">{currentScreeningExecution.execution_id}</span>],
                          ["정책", <span className="rs-mono" key="policy">{currentScreeningExecution.policy_version}</span>],
                          ["프롬프트", <span className="rs-mono" key="prompt">{currentScreeningExecution.prompt_version}</span>],
                          ["모델", <span className="rs-mono" key="model">{currentScreeningExecution.model_name}</span>],
                          ["모델 식별 해시", <span className="rs-mono" key="md">{currentScreeningExecution.model_digest}</span>],
                          ["회사 프로필", <span className="rs-mono" key="profile">{currentScreeningExecution.company_profile_version}</span>],
                          ["프로필 식별 해시", <span className="rs-mono" key="pd">{currentScreeningExecution.company_profile_digest}</span>],
                          ["입력 식별 해시", <span className="rs-mono" key="input">{currentScreeningExecution.input_artifact_digest}</span>],
                        ]}
                      />
                    ) : (
                      <Caption>
                        {screeningListReady
                          ? "조회 범위 안에 이 회차의 전량 판정 실행이 없어 고정 입력을 확인할 수 없어요."
                          : "판정 실행 목록을 확인하지 못해 고정 입력이 미확인이에요."}
                      </Caption>
                    )}
                  </Section>
                  <Section title="회차 수집 조건">
                    <Facts
                      items={[
                        ["기간", formatRunRange(detail.run_id, detail.collection_scope.window_from, detail.collection_scope.window_to)],
                        ["시간대", present(detail.collection_scope.timezone, "시간대 미확인")],
                        ["업무 구분", present(detail.collection_scope.business_area, "업무 구분 미확인")],
                        [
                          "사전규격",
                          detail.collection_scope.pre_spec_available === true
                            ? "수집 가능"
                            : detail.collection_scope.pre_spec_available === false ? "수집되지 않음" : "확인 불가",
                        ],
                        ["사전규격 사유", present(detail.collection_scope.pre_spec_reason, "상태 기록 없음")],
                        [
                          "역량 축",
                          detail.collection_scope.focus_axes.length ? detail.collection_scope.focus_axes.join(" · ") : "기록 없음",
                        ],
                        [
                          "실적 레퍼런스",
                          detail.collection_scope.performance_reference_count === null
                            ? "기록 없음"
                            : `${formatNumber(detail.collection_scope.performance_reference_count)}건`,
                        ],
                        ["판정 기준", present(detail.screening_basis, "판정 기준 미기록")],
                      ]}
                    />
                  </Section>
                  <Note title="이 실행의 입력은 고정되어 있어요">
                    현재 판정 기준이 바뀌어도 이미 시작한 실행에 소급 적용하지 않아요. 회차 원본과 기존
                    판정 기록은 덮어쓰지 않아요.
                  </Note>
                </>
              ) : null}

              {visibleTab === "order_plan_screening" && hasOrderPlans(detail.kind) ? (
                <OrderPlanScreeningPanel
                  runId={detail.run_id}
                  selectedExecutionId={orderPlanExecutionId}
                  onSelectExecution={selectOrderPlanExecution}
                />
              ) : null}
              {/* 관련 화면 링크. 이 회차가 실무 화면 어디에 걸리는지로 이어 준다.
                * 발주계획은 `전체` 보기로 연다(시안 M1 승인) — 기본 보기는 검토 대상만
                * 남기므로 회차 전체가 0건처럼 보인다. 사전규격도 같은 이유로
                * `workspace=all&sw_only=false`로 연다. */}
              {hasOrderPlans(detail.kind) || hasNotices(detail.kind) ? (
                <div className="rs-detail-links">
                  {hasOrderPlans(detail.kind) ? (
                    <Link
                      className="rs-inline-link"
                      to={`/order-plans?qwen=&source_run_id=${encodeURIComponent(detail.run_id)}`}
                    >
                      이 회차의 발주계획 보기 →
                    </Link>
                  ) : null}
                  {hasNotices(detail.kind) ? (
                    <Link
                      className="rs-inline-link"
                      to={`/pre-specs?workspace=all&sw_only=false&source_run_id=${encodeURIComponent(detail.run_id)}`}
                    >
                      이 회차의 사전규격 보기 →
                    </Link>
                  ) : null}
                  <Caption as="span">실무 화면이 `전체` 보기로 이 회차에 걸린 채 열려요.</Caption>
                </div>
              ) : null}
            </div>

            {!orderPlansOnly && <DecisionBar
              stateLabel="판정 실행"
              state={screeningState}
              note={currentScreeningExecution?.published_run_id ? "게시 완료" : "게시 전"}
              secondaryActions={(
                <>
                  <Button
                    label="파이프라인 실행"
                    size="sm"
                    icon={<SlidersHorizontal aria-hidden="true" />}
                    onClick={() => { setActionError(null); setPipelineDialogOpen(true); }}
                  />
                  {canStop ? (
                    <Button
                      label="실행 중단"
                      size="sm"
                      icon={<Pause aria-hidden="true" />}
                      onClick={() => {
                        setStopTarget(currentScreeningExecution ?? null);
                        setStopActionError(null);
                        setStopDialogOpen(true);
                      }}
                    />
                  ) : null}
                </>
              )}
              primaryAction={(
                <Button
                  aria-label="전량 판정 대기열에 넣기"
                  label="전량 판정 등록"
                  size="sm"
                  variant="primary"
                  icon={<Play aria-hidden="true" />}
                  isDisabled={startDisabled}
                  onClick={() => { setScreeningActionError(null); setStartDialogOpen(true); }}
                />
              )}
            />}
          </>
        ) : null}
      </section>

      {detail ? (
        <>
          <PipelineControlsDialog
            open={pipelineDialogOpen}
            onClose={() => setPipelineDialogOpen(false)}
            runId={detail.run_id}
            stages={detail.pipeline}
            busy={pipelineBusy}
            actionError={actionError}
            onRun={(stage, fromRaw) => void startStage(stage, fromRaw)}
          />
          <JudgmentStartDialog
            open={startDialogOpen}
            onClose={() => setStartDialogOpen(false)}
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
            executionBusy={executionBusy}
            listReady={screeningListReady}
            onRetryConfiguration={() => {
              void activationCandidatePoliciesQuery.refetch();
              void activePoliciesQuery.refetch();
              void profileSnapshotsQuery.refetch();
              void screeningExecutionsQuery.refetch();
            }}
            onStart={() => void startScreening()}
            startBusy={screeningStartBusy}
            actionError={screeningActionError}
          />
          <JudgmentStopDialog
            open={stopDialogOpen}
            onClose={() => { setStopDialogOpen(false); setStopTarget(null); }}
            runId={detail.run_id}
            target={stopTarget}
            actor={stopActor}
            onActorChange={setStopActor}
            stopBusy={screeningStopBusy}
            actionError={stopActionError}
            onConfirm={() => void stopScreening()}
          />
        </>
      ) : null}
    </SplitWorkspace>
  );
}
