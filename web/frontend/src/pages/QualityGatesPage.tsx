import { useEffect, useMemo, useRef } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { EmptyState } from "../components/common/EmptyState";
import { QualityGateCreateForm } from "../components/quality/QualityGateCreateForm";
import { QualityGateMetrics } from "../components/quality/QualityGateMetrics";
import { QualityGateReviewForm } from "../components/quality/QualityGateReviewForm";
import { QualityGateRuns } from "../components/quality/QualityGateRuns";
import { ApiError, api } from "../lib/api";
import type { QualityGateDetailResponse, QualityGateListResponse, QualityGateResponse } from "../lib/types";

const ACTIVE_GATE_STATUSES = new Set(["대기", "실행 중", "중지 요청"]);
const ACTIVE_EXECUTION_STATUSES = new Set(["대기", "실행 중", "중지 요청"]);

function gateNeedsPolling(gate: QualityGateResponse | QualityGateDetailResponse): boolean {
  if (ACTIVE_GATE_STATUSES.has(gate.execution_status)) return true;
  if ("pass_a" in gate && "pass_b" in gate) {
    return ACTIVE_EXECUTION_STATUSES.has(gate.pass_a.status) || ACTIVE_EXECUTION_STATUSES.has(gate.pass_b.status);
  }
  return false;
}

/**
 * Poll with one recursive timeout instead of an interval. The in-flight guard
 * prevents a slow API response from overlapping the next request; the
 * generation token prevents an old selection's response from touching the
 * current query cache after unmount or selection change.
 */
function useQualityGatePolling({
  shouldPoll,
  selectedGateId,
  queryClient,
}: {
  shouldPoll: boolean;
  selectedGateId: string | null;
  queryClient: ReturnType<typeof useQueryClient>;
}) {
  const generationRef = useRef(0);
  const inFlightRef = useRef(false);
  const waitingForInFlightRef = useRef(false);
  const scheduleCurrentRef = useRef<(() => void) | null>(null);
  const shouldPollRef = useRef(shouldPoll);
  shouldPollRef.current = shouldPoll;

  useEffect(() => {
    const generation = ++generationRef.current;
    let disposed = false;
    let timer: number | undefined;
    let failureCount = 0;

    const schedule = (delayMs: number) => {
      if (disposed || generation !== generationRef.current || !shouldPollRef.current) return;
      timer = window.setTimeout(async () => {
        timer = undefined;
        if (disposed || generation !== generationRef.current || !shouldPollRef.current) return;
        if (inFlightRef.current) {
          // The request that owns the timer will schedule the next one in its
          // finally path. Do not create a second timer while it is in flight.
          waitingForInFlightRef.current = true;
          return;
        }
        inFlightRef.current = true;
        const listPromise = api.getQualityGates({ limit: 100, offset: 0 });
        const detailPromise = selectedGateId ? api.getQualityGate(selectedGateId) : null;
        const [listResult, detailResult] = await Promise.allSettled([listPromise, detailPromise ?? Promise.resolve(null)]);
        const failed = listResult.status === "rejected" || detailResult.status === "rejected";
        if (!disposed && generation === generationRef.current) {
          if (listResult.status === "fulfilled") queryClient.setQueryData<QualityGateListResponse>(["quality-gates"], listResult.value);
          if (detailResult.status === "fulfilled" && detailResult.value) queryClient.setQueryData<QualityGateDetailResponse>(["quality-gate", selectedGateId], detailResult.value);
          failureCount = failed ? Math.min(failureCount + 1, 3) : 0;
        }
        inFlightRef.current = false;
        if (waitingForInFlightRef.current) {
          waitingForInFlightRef.current = false;
          scheduleCurrentRef.current?.();
        } else if (!disposed && generation === generationRef.current && shouldPollRef.current) {
          schedule(failed ? Math.min(30_000, 5_000 * (2 ** failureCount)) : 5_000);
        }
      }, delayMs);
    };

    const currentSchedule = () => schedule(5_000);
    scheduleCurrentRef.current = currentSchedule;
    schedule(5_000);
    return () => {
      disposed = true;
      ++generationRef.current;
      if (timer !== undefined) window.clearTimeout(timer);
      if (scheduleCurrentRef.current === currentSchedule) scheduleCurrentRef.current = null;
      // Do not clear inFlightRef here: a request from the previous generation
      // must finish before a new selection starts another one.
    };
  }, [queryClient, selectedGateId, shouldPoll]);
}

function queryError(error: unknown, resource: string): string {
  if (error instanceof ApiError && error.status === 409) return "최신 상태와 충돌했습니다. 목록을 새로 고치십시오.";
  if (error instanceof ApiError && error.status === 503) return "모델 상태를 확인할 수 없습니다. 잠시 후 다시 시도하십시오.";
  if (error instanceof ApiError && error.status > 0) return `${resource}을(를) 불러오지 못했습니다 (${error.status}).`;
  return `${resource}을(를) 불러오지 못했습니다.`;
}

function purposeLabel(purpose: QualityGateResponse["purpose"]): string {
  return purpose === "model_comparison" ? "모델 비교용" : "운영 승인용";
}

function resultClass(status: QualityGateResponse["result_status"]): string {
  if (status === "통과") return "quality-state-passed";
  if (status === "미달") return "quality-state-failed";
  if (status === "보류") return "quality-state-held";
  return "quality-state-unmeasured";
}

function GateList({ items, selectedId, onSelect }: { items: QualityGateResponse[]; selectedId: string | null; onSelect: (gateId: string) => void }) {
  return (
    <section className="quality-panel quality-list-panel" aria-labelledby="quality-list-heading">
      <div className="quality-panel-heading"><div><span className="quality-eyebrow">이력</span><h2 id="quality-list-heading">품질 게이트 목록</h2></div><span className="quality-readonly-note">{items.length}건</span></div>
      {items.length > 0 ? (
        <div className="quality-gate-list" role="list">
          {items.map((gate) => <button type="button" role="listitem" className={`quality-gate-list-item ${selectedId === gate.gate_id ? "is-selected" : ""}`} key={gate.gate_id} onClick={() => onSelect(gate.gate_id)} aria-pressed={selectedId === gate.gate_id}>
            <span className="quality-gate-list-title"><strong>{purposeLabel(gate.purpose)}</strong><span className={`quality-status ${resultClass(gate.result_status)}`}>{gate.result_status}</span>{gate.purpose === "model_comparison" ? <span className="quality-list-warning">운영 활성화에 사용할 수 없음</span> : null}</span>
            <span className="mono">{gate.gate_id}</span>
            <span>{gate.policy_version} · {gate.created_by}</span>
            <span className="quality-gate-list-meta">실행 {gate.execution_status} · 최신 evaluation <code>{gate.latest_evaluation_id}</code></span>
          </button>)}
        </div>
      ) : <p className="quality-empty-inline">생성된 게이트가 없습니다.</p>}
    </section>
  );
}

function GateContext({ gate }: { gate: QualityGateDetailResponse }) {
  return (
    <div className="quality-context-grid" aria-label="게이트 고정 입력">
      <div><span>정책</span><strong className="mono">{gate.policy_version}</strong></div>
      <div><span>모델</span><strong>{gate.model_name}</strong><code>{gate.model_digest}</code></div>
      <div><span>프롬프트</span><strong className="mono">{gate.prompt_version}</strong></div>
      <div><span>회사 프로필</span><strong className="mono">{gate.company_profile_version}</strong><code>{gate.company_profile_digest}</code></div>
      <div><span>표본 digest</span><code>{gate.sample_artifact_digest}</code></div>
      <div><span>기준 digest</span><code>{gate.baseline_decisions_digest}</code></div>
    </div>
  );
}

function EvaluationHistory({ gate }: { gate: QualityGateDetailResponse }) {
  return (
    <section className="quality-panel quality-evaluation-panel" aria-labelledby="quality-evaluations-heading">
      <div className="quality-panel-heading"><div><span className="quality-eyebrow">불변 revision</span><h2 id="quality-evaluations-heading">계산 이력</h2></div><span className="quality-readonly-note">최신 결과만 연결 가능</span></div>
      <div className="quality-table-wrap">
        <table className="quality-evaluation-table">
          <caption className="quality-sr-only">품질 게이트 계산 revision 이력</caption>
          <thead><tr><th scope="col">revision</th><th scope="col">evaluation ID</th><th scope="col">상태</th><th scope="col">유효 리뷰</th><th scope="col">생성 시각</th><th scope="col">사유</th></tr></thead>
          <tbody>{gate.evaluations.map((evaluation) => <tr className={evaluation.evaluation_id === gate.latest_evaluation_id ? "is-latest" : ""} key={evaluation.evaluation_id}><th scope="row">{evaluation.revision}{evaluation.evaluation_id === gate.latest_evaluation_id ? " · 최신" : ""}</th><td><code>{evaluation.evaluation_id}</code></td><td>{evaluation.result_status}</td><td>{evaluation.valid_review_count}/10 · {evaluation.distinct_notice_review_count}/10</td><td>{new Date(evaluation.created_at).toLocaleString("ko-KR")}</td><td>{evaluation.reasons.length > 0 ? evaluation.reasons.join(" ") : "사유 없음"}</td></tr>)}</tbody>
        </table>
      </div>
    </section>
  );
}

function GateDetail({ gate, onRefresh }: { gate: QualityGateDetailResponse; onRefresh: () => void }) {
  const unavailable = gate.result_status === "미측정" || gate.result_status === "보류";
  return (
    <div className="quality-detail">
      <header className="quality-detail-header">
        <div><span className="quality-eyebrow">선택한 게이트</span><h2>{purposeLabel(gate.purpose)}</h2><p className="mono">{gate.gate_id}</p></div>
        <div className={`quality-result-banner ${resultClass(gate.result_status)}`} role="status" aria-live="polite"><strong>{gate.result_status}</strong><span>{gate.execution_status}</span></div>
      </header>
      {gate.purpose === "model_comparison" ? <div className="quality-critical-warning" role="alert"><strong>운영 활성화에 사용할 수 없음</strong><span>모델 비교용 결과는 수치상 통과해도 운영 정책·상시 운영 활성화의 근거가 되지 않습니다.</span></div> : null}
      {unavailable ? <div className="quality-unavailable-notice" role="status"><strong>계산 불가 또는 보류</strong><span>A/B 실행이 종결되고 유효 리뷰 10건이 모이기 전까지 최종 품질 결과를 계산할 수 없습니다.</span></div> : null}
      <GateContext gate={gate} />
      <QualityGateRuns passA={gate.pass_a} passB={gate.pass_b} />
      <QualityGateMetrics metrics={gate.metrics} resultStatus={gate.result_status} />
      <QualityGateReviewForm gateId={gate.gate_id} reviews={gate.reviews} latestEvaluation={gate.evaluations.find((evaluation) => evaluation.evaluation_id === gate.latest_evaluation_id) ?? gate.evaluations[gate.evaluations.length - 1]} onSaved={onRefresh} />
      <EvaluationHistory gate={gate} />
    </div>
  );
}

export function QualityGatesPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const queryClient = useQueryClient();
  const selectedFromUrl = searchParams.get("gate");
  const gatesQuery = useQuery({
    queryKey: ["quality-gates"],
    queryFn: () => api.getQualityGates({ limit: 100, offset: 0 }),
    retry: false,
    refetchOnWindowFocus: false,
    staleTime: 0,
  });
  const policiesQuery = useQuery({ queryKey: ["policies"], queryFn: () => api.getPolicies(), staleTime: 10_000 });
  const selectedGateId = selectedFromUrl ?? gatesQuery.data?.items[0]?.gate_id ?? null;
  const detailQuery = useQuery({
    queryKey: ["quality-gate", selectedGateId],
    queryFn: () => api.getQualityGate(selectedGateId as string),
    enabled: Boolean(selectedGateId),
    retry: false,
    refetchOnWindowFocus: false,
    staleTime: 0,
  });
  const listItems = gatesQuery.data?.items ?? [];
  const selectedExists = useMemo(() => listItems.some((gate) => gate.gate_id === selectedGateId), [listItems, selectedGateId]);
  const shouldPoll = listItems.some(gateNeedsPolling) || (detailQuery.data ? gateNeedsPolling(detailQuery.data) : false);
  useQualityGatePolling({ shouldPoll, selectedGateId, queryClient });
  const refreshDetail = () => {
    void queryClient.invalidateQueries({ queryKey: ["quality-gate", selectedGateId] });
    void queryClient.invalidateQueries({ queryKey: ["quality-gates"] });
  };

  if (gatesQuery.isLoading || policiesQuery.isLoading) return <div className="quality-loading" role="status" aria-live="polite">품질 게이트 목록을 불러오는 중입니다.</div>;
  if (gatesQuery.error || policiesQuery.error) {
    const error = gatesQuery.error ?? policiesQuery.error;
    return <EmptyState title="품질 게이트를 불러오지 못했습니다." description={queryError(error, "품질 게이트")} action={{ label: "다시 시도", onClick: () => { void gatesQuery.refetch(); void policiesQuery.refetch(); } }} />;
  }

  return (
    <div className="quality-page">
      <header className="quality-page-header">
        <div><span className="quality-eyebrow">판정 런타임 · 검증</span><h1>품질 게이트</h1><p>모델 비교와 운영 승인을 분리하고, 불변 A/B 결과와 담당자 근거 리뷰를 함께 확인합니다.</p></div>
        <div className="quality-header-facts"><span>고정 표본</span><strong>40건</strong><span>리뷰 기준</span><strong>10건</strong></div>
      </header>
      <QualityGateCreateForm policies={policiesQuery.data} onCreated={refreshDetail} />
      <GateList items={listItems} selectedId={selectedGateId} onSelect={(gateId) => setSearchParams({ gate: gateId })} />
      {detailQuery.isLoading ? <div className="quality-loading" role="status" aria-live="polite">선택한 게이트의 A/B 상태와 지표를 확인하는 중입니다.</div> : null}
      {detailQuery.error ? <div className="quality-inline-error" role="alert">{queryError(detailQuery.error, "게이트 상세")}</div> : null}
      {detailQuery.data && selectedExists ? <GateDetail gate={detailQuery.data} onRefresh={refreshDetail} /> : null}
      {!selectedGateId && !gatesQuery.isLoading ? <EmptyState title="생성된 품질 게이트가 없습니다." description="목적·정책·담당자를 입력해 첫 게이트를 생성하십시오." /> : null}
    </div>
  );
}
