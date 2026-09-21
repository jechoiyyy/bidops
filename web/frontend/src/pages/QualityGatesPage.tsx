import { useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { Button } from "@astryxdesign/core/Button";
import { Text } from "@astryxdesign/core/Text";
import { Plus } from "lucide-react";
import {
  DataTable,
  DetailFooter,
  DetailHeader,
  DetailTabs,
  Facts,
  Note,
  Queue,
  Section,
  Small,
  StatLine,
  StateView,
  StatusToken,
} from "../components/criteria/CriteriaPrimitives";
import { QualityGateCreateDialog } from "../components/quality/QualityGateCreateDialog";
import { QualityGateMetrics } from "../components/quality/QualityGateMetrics";
import { QualityGateReviewDialog } from "../components/quality/QualityGateReviewDialog";
import { QualityGateRuns } from "../components/quality/QualityGateRuns";
import { ApiError, api } from "../lib/api";
import { formatMoment as formatMomentBase } from "../lib/format";
import type { QualityGateDetailResponse, QualityGateListResponse, QualityGateResponse } from "../lib/types";

/**
 * 품질 게이트 탭.
 *
 * 구분해서 말해야 하는 것이 넷이다.
 *
 *  1. **목적.** 모델 비교용 결과는 수치가 통과여도 운영 활성화 근거가 아니다.
 *  2. **실행 상태와 품질 결과.** A/B 실행이 종결됐다는 것은 계산이 끝났다는 뜻이지
 *     통과했다는 뜻이 아니다.
 *  3. **리뷰 건수와 통과.** 화면은 리뷰 수로 통과를 만들지 않는다. 결과는 서버의
 *     결정적 계산(`result_status`)뿐이다.
 *  4. **미측정·보류·계산 불가와 실제 0.** 수치가 없으면 0으로 바꾸지 않는다.
 */

const ACTIVE_GATE_STATUSES = new Set(["대기", "실행 중", "중지 요청"]);
const ACTIVE_EXECUTION_STATUSES = new Set(["대기", "실행 중", "중지 요청"]);

type GateDetailTab = "result" | "reviews" | "binding";

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

function queryErrorText(error: unknown, resource: string): string {
  if (error instanceof ApiError && error.status === 409) return "최신 상태와 충돌했습니다. 목록을 새로 고치십시오.";
  if (error instanceof ApiError && error.status === 503) return "모델 상태를 확인할 수 없습니다. 잠시 후 다시 시도하십시오.";
  if (error instanceof ApiError && error.status > 0) return `${resource}을(를) 불러오지 못했습니다 (${error.status}).`;
  return `${resource}을(를) 불러오지 못했습니다.`;
}

function purposeLabel(purpose: QualityGateResponse["purpose"]): string {
  return purpose === "model_comparison" ? "모델 비교" : "운영 승인";
}

/** `lib/format.ts`가 정본이다(U3, 중복 통합). 이 화면의 null 문구(`기록 없음`)만 고정한다. */
function moment(value: string | null): string {
  return formatMomentBase(value, "기록 없음");
}

/** 평가가 없거나 수치가 누락된 상태는 실제 0건과 구분한다. */
function countLabel(value: unknown): string {
  return typeof value === "number" && Number.isFinite(value) ? `${value}` : "계산 불가";
}

export function QualityGatesPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const queryClient = useQueryClient();
  const [createOpen, setCreateOpen] = useState(false);
  // 근거 리뷰 창의 대상. 열 때 한 번 정하고 창이 닫힐 때까지 바뀌지 않는다.
  const [reviewTarget, setReviewTarget] = useState<string | null>(null);

  const gatesQuery = useQuery({
    queryKey: ["quality-gates"],
    queryFn: () => api.getQualityGates({ limit: 100, offset: 0 }),
    retry: false,
    refetchOnWindowFocus: false,
    staleTime: 0,
  });
  const policiesQuery = useQuery({ queryKey: ["policies"], queryFn: () => api.getPolicies(), staleTime: 10_000 });

  const listItems = gatesQuery.data?.items ?? [];
  const selectedFromUrl = searchParams.get("gate");
  const selectedGateId = selectedFromUrl ?? listItems[0]?.gate_id ?? null;
  const detailQuery = useQuery({
    queryKey: ["quality-gate", selectedGateId],
    queryFn: () => api.getQualityGate(selectedGateId as string),
    enabled: Boolean(selectedGateId),
    retry: false,
    refetchOnWindowFocus: false,
    staleTime: 0,
  });
  const rawDetailTab = searchParams.get("gtab");
  const detailTab: GateDetailTab = rawDetailTab === "reviews" || rawDetailTab === "binding" ? rawDetailTab : "result";

  const shouldPoll = listItems.some(gateNeedsPolling) || (detailQuery.data ? gateNeedsPolling(detailQuery.data) : false);
  useQualityGatePolling({ shouldPoll, selectedGateId, queryClient });

  // 선택 ID와 상세 탭만 바꾸고 회차 등 다른 파라미터는 그대로 둔다.
  function updateParams(changes: Record<string, string | null>) {
    setSearchParams((current) => {
      const next = new URLSearchParams(current);
      for (const [key, value] of Object.entries(changes)) {
        if (value === null || value === "") next.delete(key);
        else next.set(key, value);
      }
      return next;
    }, { replace: true });
  }

  function refreshDetail() {
    void queryClient.invalidateQueries({ queryKey: ["quality-gate", selectedGateId] });
    void queryClient.invalidateQueries({ queryKey: ["quality-gates"] });
  }

  if (gatesQuery.isPending || policiesQuery.isPending) {
    return (
      <div className="crit-workspace" id="criteria-panel-quality-gates" role="tabpanel">
        <StateView description="게이트 목록과 정책을 확인하는 중입니다." kind="loading" title="품질 게이트를 불러오는 중입니다" />
      </div>
    );
  }
  if (gatesQuery.error || policiesQuery.error) {
    return (
      <div className="crit-workspace" id="criteria-panel-quality-gates" role="tabpanel">
        <StateView
          action={<Button label="다시 조회" onClick={() => { void gatesQuery.refetch(); void policiesQuery.refetch(); }} />}
          description={queryErrorText(gatesQuery.error ?? policiesQuery.error, "품질 게이트")}
          kind="error"
          title="품질 게이트를 불러오지 못했습니다."
        />
      </div>
    );
  }

  const gate = detailQuery.data ?? null;
  const comparison = gate?.purpose === "model_comparison";
  const latestEvaluation = gate
    ? gate.evaluations.find((evaluation) => evaluation.evaluation_id === gate.latest_evaluation_id)
      ?? gate.evaluations[gate.evaluations.length - 1]
    : undefined;
  const validCount = typeof latestEvaluation?.valid_review_count === "number" ? latestEvaluation.valid_review_count : null;
  const distinctCount = typeof latestEvaluation?.distinct_notice_review_count === "number" ? latestEvaluation.distinct_notice_review_count : null;

  return (
    <div className="crit-workspace" id="criteria-panel-quality-gates" role="tabpanel">
      <Queue
        count={gatesQuery.data?.total ?? listItems.length}
        emptyText="생성된 게이트가 없습니다."
        footer="목적과 최신 평가 결과를 구분합니다 · 고정 표본 40건"
        items={listItems.map((item) => ({
          id: item.gate_id,
          title: `${purposeLabel(item.purpose)} 검증`,
          // 목적이 같은 게이트가 여러 개일 수 있으므로 gate_id를 함께 적는다.
          // 서버에 게이트 이름 필드가 없어 목적만으로는 행을 구별할 수 없다.
          subtitle: `${item.gate_id}`,
          status: item.result_status,
          meta: `${item.policy_version} · ${item.model_name} · ${moment(item.created_at)} · 실행 ${item.execution_status}${item.purpose === "model_comparison" ? " · 운영 활성화에 사용 불가" : ""}`,
        }))}
        onSelect={(id) => updateParams({ gate: id })}
        selectedId={selectedGateId}
        title="품질 게이트 목록"
        tools={<Button icon={<Plus aria-hidden="true" />} label="새 품질 게이트" onClick={() => setCreateOpen(true)} size="sm" width="100%" />}
      />
      <section aria-label="선택한 품질 게이트" className="crit-detail">
        {detailQuery.isPending && selectedGateId ? (
          <StateView description="A/B 실행 상태와 지표를 확인하는 중입니다." kind="loading" title="게이트 상세를 불러오는 중입니다" />
        ) : null}
        {/* 상세 조회 실패를 "게이트 없음"으로 접지 않는다. */}
        {detailQuery.error ? (
          <StateView
            action={<Button label="다시 조회" onClick={() => { void detailQuery.refetch(); }} />}
            description={`${queryErrorText(detailQuery.error, "게이트 상세")} 선택한 게이트가 없어진 것이 아니라 상태를 확인하지 못한 것입니다.`}
            kind="error"
            title="선택한 게이트의 상세를 불러오지 못했습니다."
          />
        ) : null}
        {!selectedGateId && !detailQuery.error ? (
          <StateView
            action={<Button icon={<Plus aria-hidden="true" />} label="새 품질 게이트" onClick={() => setCreateOpen(true)} />}
            description="목적·정책·담당자를 입력해 첫 게이트를 만들면 A/B 검증 실행이 시작됩니다."
            kind="empty"
            title="생성된 품질 게이트가 없습니다."
          />
        ) : null}
        {gate && !detailQuery.error ? (
          <>
            <DetailHeader eyebrow="품질 게이트 · 고정 표본 40건" status={gate.result_status} title={`${purposeLabel(gate.purpose)} 검증`}>
              <Small>{`${gate.gate_id} · 최신 평가 ${latestEvaluation ? `수정본 ${latestEvaluation.revision}` : "없음"} · 실행 ${gate.execution_status}`}</Small>
            </DetailHeader>
            <DetailTabs
              id="criteria-gate"
              items={[["result", "검증 결과"], ["reviews", "담당자 리뷰"], ["binding", "고정 입력·이력"]]}
              onChange={(value) => updateParams({ gtab: value === "result" ? null : value })}
              value={detailTab}
            />
            <div className="crit-detail-scroll" id={`criteria-gate-${detailTab}`} role="tabpanel">
              {comparison ? (
                <Note role="alert" title="모델 비교 결과는 운영 활성화에 사용할 수 없습니다" tone="warning">
                  수치가 통과해도 정책 활성화와 상시 운영 승인에는 연결하지 않습니다.
                </Note>
              ) : null}

              {detailTab === "result" ? (
                <>
                  <StatLine items={[
                    ["A 실행", `${gate.pass_a.status} · ${gate.pass_a.completed_count}건`],
                    ["B 실행", `${gate.pass_b.status} · ${gate.pass_b.completed_count}건`],
                    ["유효 리뷰", `${countLabel(validCount)} / 10건`],
                  ]} />
                  {gate.result_status === "미측정" || gate.result_status === "보류" ? (
                    <Note role="status" title={`최종 품질 결과 · ${gate.result_status}`} tone="warning">
                      A/B 실행이 종결되고 유효 리뷰 10건·서로 다른 공고 10건이 모이기 전까지 최종 품질 결과를 계산할 수 없습니다. 계산 보류는 미달이 아닙니다.
                    </Note>
                  ) : null}
                  <QualityGateRuns passA={gate.pass_a} passB={gate.pass_b} />
                  <QualityGateMetrics metrics={gate.metrics} resultStatus={gate.result_status} />
                  {gate.reasons.length > 0 ? (
                    <Section title="최신 평가 사유">
                      <ul>{gate.reasons.map((reason) => <li key={reason}>{reason}</li>)}</ul>
                    </Section>
                  ) : null}
                </>
              ) : null}

              {detailTab === "reviews" ? (
                <>
                  <StatLine items={[
                    ["유효 리뷰", `${countLabel(validCount)} / 10건`],
                    ["서로 다른 공고", `${countLabel(distinctCount)} / 10건`],
                    ["저장된 리뷰", `${gate.reviews.length}건`],
                  ]} />
                  <Section title={`담당자 근거 리뷰 · ${gate.reviews.length}건`}>
                    {gate.reviews.length > 0 ? (
                      <DataTable
                        caption="담당자 리뷰 목록"
                        headings={["공고", "담당자", "근거 판단", "판정 식별 해시", "수정 시각"]}
                        rows={gate.reviews.map((review) => [
                          <code key="n">{review.notice_id}</code>,
                          <Text key="r">{review.reviewer}</Text>,
                          <Text key="j">{review.evidence_judgment}</Text>,
                          <code key="d">{review.decision_digest}</code>,
                          <Text key="u">{moment(review.updated_at)}</Text>,
                        ])}
                      />
                    ) : <Small>아직 저장된 리뷰가 없습니다. 0건이며 계산 실패와는 다른 상태입니다.</Small>}
                  </Section>
                  <Note title="리뷰 저장 뒤 평가 결과를 다시 확인합니다">
                    리뷰는 Pass A 판정의 식별 해시에 묶입니다. 판단 보류와 식별 해시 불일치는 유효 분모에서 빠지며,
                    리뷰 개수가 채워졌다는 이유만으로 화면이 통과 판정을 만들지 않습니다.
                  </Note>
                </>
              ) : null}

              {detailTab === "binding" ? (
                <>
                  <Section title="고정 입력">
                    <Facts items={[
                      ["정책", <span className="crit-mono" key="p">{gate.policy_version}</span>],
                      ["프롬프트", <span className="crit-mono" key="pr">{gate.prompt_version}</span>],
                      ["모델", <span key="m">{gate.model_name} · <code>{gate.model_digest}</code></span>],
                      ["회사 프로필", <span key="c">{gate.company_profile_version} · <code>{gate.company_profile_digest}</code></span>],
                      ["기준 회차", <span className="crit-mono" key="r">{gate.baseline_run_id}</span>],
                      ["표본 식별 해시", <code key="s">{gate.sample_artifact_digest}</code>],
                      ["기준 판정 식별 해시", <code key="b">{gate.baseline_decisions_digest}</code>],
                      ["Pass A · Pass B 실행", <span className="crit-mono" key="ab">{gate.pass_a_execution_id} · {gate.pass_b_execution_id}</span>],
                      ["생성", `${moment(gate.created_at)} · ${gate.created_by}`],
                      ["종결", moment(gate.completed_at)],
                    ]} />
                  </Section>
                  <Section title={`계산 이력 · 수정본 ${gate.evaluations.length}건`}>
                    <DataTable
                      caption="품질 게이트 계산 수정본 이력"
                      headings={["수정본", "평가 ID", "결과", "유효 리뷰", "생성 시각", "사유"]}
                      rows={gate.evaluations.map((evaluation) => [
                        <Text key="rev" weight="semibold">{`${evaluation.revision}${evaluation.evaluation_id === gate.latest_evaluation_id ? " · 최신" : ""}`}</Text>,
                        <code key="id">{evaluation.evaluation_id}</code>,
                        <StatusToken key="st" label={evaluation.result_status} />,
                        <Text key="c">{`${countLabel(evaluation.valid_review_count)}/10 · ${countLabel(evaluation.distinct_notice_review_count)}/10`}</Text>,
                        <Text key="t">{moment(evaluation.created_at)}</Text>,
                        <Text key="r">{evaluation.reasons.length > 0 ? evaluation.reasons.join(" ") : "사유 없음"}</Text>,
                      ])}
                    />
                    <Small>계산 이력은 덧붙기만 하며 이전 수정본을 덮지 않습니다. 활성화에 연결할 수 있는 것은 최신 수정본뿐입니다.</Small>
                  </Section>
                </>
              ) : null}
            </div>
            <DetailFooter note={comparison ? "모델 비교용 · 운영 활성화에 연결 불가" : "운영 승인용 · 최신 통과 평가만 정책 활성화에 연결 가능"}>
              <Button isDisabled={!selectedGateId} label="근거 리뷰 작성" onClick={() => setReviewTarget(selectedGateId)} size="sm" variant="primary" />
            </DetailFooter>
          </>
        ) : null}
      </section>
      <QualityGateCreateDialog
        onClose={() => setCreateOpen(false)}
        onCreated={(gateId) => {
          setCreateOpen(false);
          updateParams({ gate: gateId, gtab: null });
          refreshDetail();
        }}
        open={createOpen}
        policies={policiesQuery.data}
      />
      {/* 대상은 **여는 순간**에 정해지고 창이 살아 있는 동안 바뀌지 않는다.
        * `key`가 대상이므로 다른 게이트로 열면 새로 마운트돼 공고·담당자·판단·
        * 메모가 모두 비고, 같은 창 안에서 409가 나면 초안은 그대로 남는다.
        * 저장이 진행 중일 때 주소나 목록 선택이 바뀌어도 이 창은 자기 대상에만
        * 저장한다 — `reviewTarget`은 `selectedGateId`를 따라가지 않는다. */}
      <QualityGateReviewDialog
        gateId={reviewTarget}
        key={reviewTarget ?? "closed"}
        onClose={() => setReviewTarget(null)}
        onSaved={() => {
          setReviewTarget(null);
          refreshDetail();
        }}
      />
    </div>
  );
}
