import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { ActorField } from "../components/common/ActorField";
import { EmptyState } from "../components/common/EmptyState";
import { MutationFeedback } from "../components/common/MutationFeedback";
import { Panel } from "../components/common/Panel";
import {
  ReviewDecisionAction,
  ReviewHistoryLinkRail,
  ReviewRevisionHistory,
  ReviewValue,
  StickyDecisionHeader,
} from "../components/common/ReviewPrimitives";
import { StatusBadge, type StatusTone } from "../components/common/StatusBadge";
import { api, ApiError } from "../lib/api";
import type {
  OrderPlanFeedbackPriority,
  OrderPlanRelevance,
  OrderPlanScreeningExecutionDetailResponse,
  OrderPlanScreeningFeedbackView,
  OrderPlanScreeningHistoryItem,
} from "../lib/types";
import "../styles/order-plans.css";
import "../styles/detail-skeleton.css";

const EMPTY_HISTORY: OrderPlanScreeningHistoryItem[] = [];
const EMPTY_FEEDBACK: OrderPlanScreeningFeedbackView[] = [];
const RELEVANCE_OPTIONS: OrderPlanRelevance[] = ["relevant", "uncertain", "not_relevant"];
const PRIORITY_OPTIONS: OrderPlanFeedbackPriority[] = ["high", "medium", "low"];

function formatMoment(value: string | null | undefined): string {
  if (!value) return "미확인";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString("ko-KR");
}

function formatNumber(value: number | null | undefined): string {
  return value === null || value === undefined ? "null (미측정)" : value.toLocaleString("ko-KR");
}

function formatNullableMoment(value: string | null): string {
  return value === null ? "null" : formatMoment(value);
}

function formatScore(value: number | null): string {
  return value === null ? "null (값 없음/미측정)" : value.toLocaleString("ko-KR", { maximumFractionDigits: 4 });
}

function textOrUnknown(value: string | null | undefined): string {
  return value && value.trim() ? value : "미확인";
}

function statusTone(status: string | null | undefined): StatusTone {
  if (status === "성공" || status === "relevant" || status === "selected") return "success";
  if (status === "부분 성공" || status === "uncertain" || status === "실행 중" || status === "중지 요청") return "warning";
  if (status === "실패" || status === "failed" || status === "rejected" || status === "not_relevant") return "danger";
  if (status === "대기" || status === "unknown" || status === "not_attempted") return "info";
  return "neutral";
}

function requestId(): string {
  if (typeof globalThis.crypto?.randomUUID === "function") return globalThis.crypto.randomUUID();
  throw new Error("브라우저가 계약에 필요한 UUID 생성을 지원하지 않습니다.");
}

function plannedTiming(year: string | null, month: string | null): string {
  if (year === null && month === null) return "null (계획 시기 미제공)";
  return `${year ?? "null"}년 ${month ?? "null"}월`;
}

function ExecutionHistoryCard({
  item,
  detail,
  pending,
  error,
}: {
  item: OrderPlanScreeningHistoryItem;
  detail: OrderPlanScreeningExecutionDetailResponse | undefined;
  pending: boolean;
  error: unknown;
}) {
  return (
    <article className="c2-history-card">
      <header className="c2-history-heading">
        <div>
          <p className="c2-card-eyebrow">execution</p>
          <h4 className="mono">{item.execution_id}</h4>
          <p className="c2-muted">source run <span className="mono">{item.source_run_id}</span></p>
        </div>
        <StatusBadge label={item.execution_status} tone={statusTone(item.execution_status)} />
      </header>

      <div className="c2-history-meta">
        <div><dt>policy version</dt><dd className="mono">{item.policy_version}</dd></div>
        <div><dt>policy hash</dt><dd className="c2-digest">{item.policy_sha256}</dd></div>
        <div><dt>binding hash</dt><dd className="c2-digest">{item.binding_sha256}</dd></div>
        <div><dt>feedback revisions</dt><dd>{item.feedback_revision_count}</dd></div>
      </div>

      <div className="c2-signal-grid">
        <section className="c2-signal c2-signal-bm25" aria-label={`${item.execution_id} BM25 결과`}>
          <h5>BM25 단계 결과</h5>
          <dl>
            <div><dt>status</dt><dd><StatusBadge label={item.stage1_status} tone={statusTone(item.stage1_status)} /></dd></div>
            <div><dt>rank</dt><dd>{item.stage1_rank === null ? "null (값 없음/미측정)" : item.stage1_rank}</dd></div>
            <div><dt>score</dt><dd>{formatScore(item.stage1_score)}</dd></div>
            <div><dt>nearest capability</dt><dd>{item.nearest_capability ?? "null (미제공)"}</dd></div>
            <div><dt>batch</dt><dd className="mono">{item.batch_id ?? "null (미적용)"}</dd></div>
            <div><dt>attempt</dt><dd>{item.attempt_no === null ? "null (미적용)" : item.attempt_no}</dd></div>
          </dl>
        </section>
        <section className="c2-signal c2-signal-qwen" aria-label={`${item.execution_id} Qwen 결과`}>
          <h5>Qwen relevance 단계 결과</h5>
          <dl>
            <div><dt>status</dt><dd><StatusBadge label={item.stage2_status} tone={statusTone(item.stage2_status)} /></dd></div>
            <div><dt>relevance</dt><dd>{item.qwen_relevance ?? "null (값 없음/미적용)"}</dd></div>
            <div><dt>score</dt><dd>{formatScore(item.qwen_score)}</dd></div>
            <div><dt>reason</dt><dd>{item.qwen_reason ?? "null (근거 미제공)"}</dd></div>
          </dl>
        </section>
      </div>

      <section className="c2-attempt-summary" aria-label={`${item.execution_id} 시도 및 실패 정보`}>
        <h5>attempt / failure 정보</h5>
        {pending ? <p className="c2-muted" role="status">실행 상세를 불러오는 중…</p> : null}
        {error ? <p className="c2-inline-warning" role="alert">실행 상세를 불러오지 못했습니다. 실패 행을 성공이나 0건으로 해석하지 않습니다.</p> : null}
        {!pending && !error && detail ? (
          <>
            <p>batch failure count: <strong>{detail.counts.failure_count}</strong>건</p>
            {detail.attempts.length ? (
              <ol className="c2-attempt-list">
                {detail.attempts.map((attempt) => (
                  <li key={attempt.attempt_id}>
                    <strong>batch {attempt.batch_id} · attempt {attempt.attempt_no}</strong>
                    <dl className="c2-attempt-grid">
                      <div><dt>model / revision</dt><dd>{attempt.model_name} · <span className="c2-digest">{attempt.model_digest}</span></dd></div>
                      <div><dt>prompt</dt><dd>{attempt.prompt_version} · <span className="c2-digest">{attempt.prompt_sha256}</span></dd></div>
                      <div><dt>profile</dt><dd>{attempt.company_profile_version} · <span className="c2-digest">{attempt.company_profile_sha256}</span></dd></div>
                      <div><dt>generation config</dt><dd className="c2-digest">{attempt.generation_config_sha256}</dd></div>
                      <div><dt>status</dt><dd><StatusBadge label={attempt.attempt_status} tone={statusTone(attempt.attempt_status)} /></dd></div>
                      <div><dt>failure</dt><dd>{attempt.failure_type ?? "null"} · {attempt.failure_code ?? "null"}</dd></div>
                      <div><dt>tokens (input / cached / output / total)</dt><dd>{formatNumber(attempt.input_tokens)} / {formatNumber(attempt.cached_input_tokens)} / {formatNumber(attempt.output_tokens)} / {formatNumber(attempt.total_tokens)}</dd></div>
                      <div><dt>duration_ms</dt><dd>{formatNumber(attempt.duration_ms)}</dd></div>
                      <div><dt>시각</dt><dd>{formatNullableMoment(attempt.started_at)} → {formatNullableMoment(attempt.finished_at)}</dd></div>
                    </dl>
                  </li>
                ))}
              </ol>
            ) : <p>attempt 기록 없음 (서버 응답)</p>}
            {detail.error_code !== null ? <p>execution error code: <span className="mono">{detail.error_code}</span></p> : <p>execution error code: null (서버 미제공)</p>}
          </>
        ) : null}
      </section>

      {!pending && !error && detail?.artifacts.length ? (
        <section className="c2-artifact-summary">
          <h5>안전한 artifact 요약</h5>
          <ul>
            {detail.artifacts.map((artifact) => (
              <li key={`${artifact.kind}-${artifact.sha256}`}>
                <span>{artifact.kind}</span>
                <StatusBadge label={artifact.validation_status} tone={artifact.validation_status === "valid" ? "success" : artifact.validation_status === "invalid" ? "danger" : "warning"} />
                <span>{artifact.byte_count.toLocaleString("ko-KR")} bytes</span>
                <span className="c2-digest">{artifact.sha256}</span>
              </li>
            ))}
          </ul>
          <p className="c2-muted">artifact metadata만 표시하며 원문·객체 경로·다운로드 동작은 제공하지 않습니다.</p>
        </section>
      ) : null}
    </article>
  );
}

const FEEDBACK_FORM_ID = "c2-detail-feedback-form";

function FeedbackForm({
  formId,
  orderPlanPk,
  executionId,
  expectedRevision,
  onReadyChange,
  onSaved,
}: {
  /** 헤더의 저장 액션이 `form` 속성으로 이 폼을 submit한다. 전제조건과 저장
   * 동작이 한 곳에만 있어 업무 규칙이 복제되지 않는다. */
  formId: string;
  orderPlanPk: number;
  executionId: string;
  expectedRevision: number;
  /** 헤더 액션의 비활성 여부를 이 폼의 준비 상태와 같게 유지한다. */
  onReadyChange: (ready: boolean) => void;
  onSaved: () => void;
}) {
  const queryClient = useQueryClient();
  const [relevance, setRelevance] = useState<OrderPlanRelevance>("uncertain");
  const [priority, setPriority] = useState<OrderPlanFeedbackPriority | "">("");
  const [memo, setMemo] = useState("");
  const [actorName, setActorName] = useState("");

  const mutation = useMutation({
    mutationFn: () => api.createOrderPlanScreeningFeedback(orderPlanPk, {
      schema_version: "feedback-create-request.v1",
      producer: "human-review-client",
      consumer: "review-api",
      request_id: requestId(),
      execution_id: executionId,
      relevance,
      priority: priority || null,
      memo: memo.trim() || null,
      expected_revision: expectedRevision,
    }, actorName),
    onSuccess: async () => {
      setMemo("");
      setActorName("");
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["order-plan-c2", "feedback", orderPlanPk] }),
        queryClient.invalidateQueries({ queryKey: ["order-plan-c2", "plan", orderPlanPk] }),
        queryClient.invalidateQueries({ queryKey: ["order-plan-c2", "list"] }),
      ]);
      onSaved();
    },
  });

  const ready = actorName.trim().length > 0 && executionId.length > 0 && !mutation.isPending;
  useEffect(() => {
    onReadyChange(ready);
  }, [onReadyChange, ready]);

  return (
    <form
      className="c2-feedback-form"
      id={formId}
      onSubmit={(event) => {
        event.preventDefault();
        if (ready) mutation.mutate();
      }}
    >
      <h4>사람 relevance / priority / note 기록</h4>
      <p className="c2-form-note">새 revision을 append-only로 추가합니다. tracking 상태·fitness grade·readiness·최종 Go/No-Go를 변경하지 않습니다.</p>
      <div className="c2-form-grid">
        <label>
          <span>relevance</span>
          <select value={relevance} onChange={(event) => setRelevance(event.target.value as OrderPlanRelevance)}>
            {RELEVANCE_OPTIONS.map((value) => <option key={value} value={value}>{value}</option>)}
          </select>
        </label>
        <label>
          <span>priority</span>
          <select value={priority} onChange={(event) => setPriority(event.target.value as OrderPlanFeedbackPriority | "")}>
            <option value="">null (미지정)</option>
            {PRIORITY_OPTIONS.map((value) => <option key={value} value={value}>{value}</option>)}
          </select>
        </label>
      </div>
      <label>
        <span>note</span>
        <textarea rows={3} value={memo} onChange={(event) => setMemo(event.target.value)} placeholder="사람 검토 근거 또는 다음 확인 사항" />
      </label>
      <ActorField value={actorName} onChange={setActorName} label="담당자 claimed name" placeholder="예: 홍길동" autoComplete="off" />
      <p className="c2-muted">대상 execution <span className="mono">{executionId}</span> · expected revision {expectedRevision}</p>
      {mutation.isError ? <MutationFeedback tone="error">{mutation.error instanceof ApiError ? mutation.error.message : "사람 피드백을 저장하지 못했습니다."}</MutationFeedback> : null}
      {mutation.isSuccess ? <MutationFeedback tone="success">새 사람 피드백 revision을 저장했습니다.</MutationFeedback> : null}
      {/* 헤더의 `새 revision 저장`과 같은 submit이다. 이름을 달리해 두 버튼이
          같은 이름으로 두 번 잡히지 않게 한다(입찰 변경 비교와 같은 방식). */}
      <button className="c2-button" type="submit" disabled={!ready}>
        {mutation.isPending ? "저장 중…" : "사람 피드백 revision 저장"}
      </button>
    </form>
  );
}

export function OrderPlanDetailPage() {
  const { orderPlanPk: orderPlanPkParam } = useParams();
  const [searchParams] = useSearchParams();
  const orderPlanPk = Number(orderPlanPkParam);
  const returnPath = `/order-plans${searchParams.toString() ? `?${searchParams.toString()}` : ""}`;
  const [selectedExecutionId, setSelectedExecutionId] = useState("");
  const [savedMessage, setSavedMessage] = useState<string | null>(null);
  const [feedbackReady, setFeedbackReady] = useState(false);
  const feedbackPanelRef = useRef<HTMLDivElement>(null);
  const handleFeedbackReadyChange = useCallback((ready: boolean) => setFeedbackReady(ready), []);
  const focusFeedbackForm = useCallback(() => {
    const panel = feedbackPanelRef.current;
    if (!panel) return;
    panel.scrollIntoView({ block: "start" });
    panel.querySelector<HTMLElement>("select, input, textarea")?.focus({ preventScroll: true });
  }, []);

  const detailQuery = useQuery({
    queryKey: ["order-plan-c2", "plan", orderPlanPk],
    queryFn: ({ signal }) => api.getOrderPlan(orderPlanPk, { signal }),
    enabled: Number.isInteger(orderPlanPk) && orderPlanPk > 0,
    staleTime: 15_000,
  });
  const historyQuery = useQuery({
    queryKey: ["order-plan-c2", "history", orderPlanPk],
    queryFn: ({ signal }) => api.getOrderPlanScreeningHistory(orderPlanPk, { signal }),
    enabled: Number.isInteger(orderPlanPk) && orderPlanPk > 0,
    staleTime: 15_000,
  });
  const feedbackQuery = useQuery({
    queryKey: ["order-plan-c2", "feedback", orderPlanPk],
    queryFn: ({ signal }) => api.getOrderPlanScreeningFeedback(orderPlanPk, null, { signal }),
    enabled: Number.isInteger(orderPlanPk) && orderPlanPk > 0,
    staleTime: 15_000,
  });

  const history = historyQuery.data?.items ?? detailQuery.data?.screening_history ?? EMPTY_HISTORY;
  const executionDetails = useQueries({
    queries: history.map((item) => ({
      queryKey: ["order-plan-c2", "execution-detail", item.execution_id],
      queryFn: ({ signal }: { signal: AbortSignal }) => api.getOrderPlanScreeningExecution(item.execution_id, { signal }),
      staleTime: 15_000,
    })),
  });
  const feedback = feedbackQuery.data?.items ?? EMPTY_FEEDBACK;

  useEffect(() => {
    if (!history.length) {
      if (selectedExecutionId) setSelectedExecutionId("");
      return;
    }
    if (!history.some((item) => item.execution_id === selectedExecutionId)) setSelectedExecutionId(history[0].execution_id);
  }, [history, selectedExecutionId]);

  const selectedFeedback = useMemo(
    () => feedback.filter((item) => item.execution_id === selectedExecutionId),
    [feedback, selectedExecutionId],
  );
  const expectedRevision = selectedFeedback.reduce((highest, item) => Math.max(highest, item.revision), 0);

  if (!Number.isInteger(orderPlanPk) || orderPlanPk <= 0) {
    return <EmptyState tone="error" title="올바른 발주계획 식별자가 필요합니다." action={{ label: "목록으로", to: "/order-plans" }} />;
  }

  const latestFeedback = detailQuery.data?.latest_human_feedback ?? null;
  const latestExecution = history.length > 0 ? history[0] : null;
  const feedbackDisabledReason = feedbackReady
    ? undefined
    : "새 revision을 저장하려면 본문의 사람 판단 입력에서 담당자 claimed name을 입력하십시오.";

  return (
    <section className="c2-page c2-detail-page detail-skeleton" data-astryx-theme="bidops" aria-labelledby="order-plan-detail-title">
      {/* 상세 3종 공통 골격(PLAN 단계 F 작업 1): 요약 헤더 → 헤더 고정 상태·결정
          action → 본문 반복 목록 → 우측 이력·연결 rail. 세 화면이 같은
          primitive(StickyDecisionHeader·ReviewHistoryLinkRail)를 쓴다.

          되돌릴 수 없는 입력 form은 헤더에 올리지 않는다(단계 F 완료 게이트).
          헤더에는 저장 액션과 입력으로 가는 이동만 두고, 폼 자체는 본문 열에
          둔다 — 시안 `OrderPlanDetail`이 사람 피드백 revision 이력과 새 revision
          입력을 본문 열에 함께 두는 배치다. 저장 버튼은 form 속성으로 본문 폼을
          submit하므로 전제조건이 한 곳에만 있다. */}
      <StickyDecisionHeader className="c2-page-header detail-skeleton-head" label="발주계획 상세 결정 헤더">
        <div className="detail-skeleton-head-top">
          <div>
            <Link className="c2-back-link" to={returnPath}>← 발주계획 목록</Link>
            <p className="c2-kicker">발주계획 C-2 상세</p>
            <h2 id="order-plan-detail-title">{detailQuery.data ? textOrUnknown(detailQuery.data.title) : "발주계획 상세"}</h2>
          </div>
          <div className="c2-contract-note">relevance는 tracking/등급/준비/최종 결정과 다른 상태축</div>
        </div>

        <div className="detail-skeleton-status-row">
          {latestExecution ? <StatusBadge label={`최근 실행 ${latestExecution.execution_status}`} tone={statusTone(latestExecution.execution_status)} /> : null}
          <StatusBadge
            label={latestFeedback ? `최근 피드백 rev ${latestFeedback.revision}` : "피드백 없음"}
            tone={latestFeedback ? statusTone(latestFeedback.relevance) : "neutral"}
          />
          <div className="detail-skeleton-actions">
            {selectedExecutionId ? (
              <>
                <ReviewDecisionAction
                  className="c2-button"
                  disabledReason={feedbackDisabledReason}
                  disabledReasonId="c2-detail-feedback-disabled"
                  form={FEEDBACK_FORM_ID}
                  isDisabled={!feedbackReady}
                  label="새 revision 저장"
                  type="submit"
                  variant="primary"
                />
                <button className="c2-button c2-button-secondary" type="button" onClick={focusFeedbackForm}>
                  사람 판단 입력으로 이동
                </button>
              </>
            ) : <p className="c2-muted">피드백을 기록할 execution history가 없습니다.</p>}
          </div>
        </div>
        {savedMessage ? <MutationFeedback tone="success">{savedMessage}</MutationFeedback> : null}
      </StickyDecisionHeader>

      <p className="c2-page-lede">관측·단계 결과·시도/실패 투영·안전한 artifact·사람 피드백 revision을 한 건 단위로 확인합니다.</p>
      <p className="c2-semantics-note"><code>filtered_out</code>·<code>not_relevant</code>·<code>unknown</code>·<code>null</code>은 각각 BM25 탈락·relevance 음성·정보 부족·값 없음/미적용을 뜻하며 서로 대체하지 않습니다.</p>

      {detailQuery.isPending ? <p className="c2-loading" role="status">발주계획 상세를 불러오는 중…</p> : null}
      {detailQuery.isError || !detailQuery.data ? (
        <EmptyState
          tone="error"
          title="발주계획 상세를 불러오지 못했습니다."
          description={detailQuery.error instanceof ApiError ? detailQuery.error.message : "계약에 맞는 상세 응답이 없습니다."}
          action={{ label: "목록으로", to: returnPath }}
        />
      ) : null}

      {detailQuery.data ? (
        <div className="detail-skeleton-grid">
          <div className="detail-skeleton-main">
            <Panel className="c2-detail-facts" title="발주계획 사실">
              <div className="c2-plan-identity">
                <div>
                  <p className="c2-card-eyebrow">계획 ID</p>
                  <p className="c2-large-id mono">{detailQuery.data.order_plan_pk}</p>
                </div>
                <div><dt>발주계획 번호</dt><dd className="mono">{detailQuery.data.order_plan_unty_no}</dd></div>
                <div><dt>기관</dt><dd>{textOrUnknown(detailQuery.data.agency_name)}</dd></div>
                <div><dt>사업 분야</dt><dd>{textOrUnknown(detailQuery.data.business_division)}</dd></div>
                <div><dt>분야 코드</dt><dd className="mono">{detailQuery.data.business_division_code ?? "null (미제공)"}</dd></div>
                <div><dt>서비스 유형</dt><dd>{detailQuery.data.service_type ?? "null (미제공)"}</dd></div>
                <div><dt>예산</dt><dd>{detailQuery.data.budget_amount === null ? "null (미제공)" : detailQuery.data.budget_amount.toLocaleString("ko-KR")}</dd></div>
                <div><dt>계획 시기</dt><dd>{plannedTiming(detailQuery.data.planned_order_year, detailQuery.data.planned_order_month)}</dd></div>
              </div>
            </Panel>

            {/* 시안 `OrderPlanDetail`은 사람 피드백 revision 이력과 새 revision
                입력을 **본문 열**에 함께 둔다. 이력을 우측 레일에 두면 지금
                저장하려는 값과 직전 revision을 한눈에 대조할 수 없다. 레일은
                관측·실행 이력과 연결만 담는다. */}
            <div ref={feedbackPanelRef}>
              <Panel
                className="c2-feedback-panel"
                title="사람 피드백 revision history"
                action={<span className="c2-muted">append-only · {feedback.length.toLocaleString("ko-KR")}건</span>}
              >
                <ReviewRevisionHistory
                  className="c2-feedback-history"
                  empty="사람 피드백이 없습니다. 사람 relevance·priority·note를 새 revision으로 기록할 수 있습니다."
                  entries={feedback.map((item) => ({
                    actor: item.claimed_name,
                    at: formatMoment(item.created_at),
                    body: (
                      <dl>
                        <div><dt>priority</dt><dd>{item.priority ?? "null (미지정)"}</dd></div>
                        <div><dt>note</dt><dd>{item.memo ?? "null (메모 미제공)"}</dd></div>
                        <div><dt>execution</dt><dd className="mono">{item.execution_id}</dd></div>
                      </dl>
                    ),
                    id: item.feedback_id,
                    revision: item.revision,
                    tags: <StatusBadge label={item.relevance} tone={statusTone(item.relevance)} />,
                  }))}
                  error={feedbackQuery.isError ? "사람 피드백 history를 불러오지 못했습니다. 저장 전 현재 revision을 확인할 수 없습니다." : undefined}
                  headingLevel={4}
                  label="사람 피드백 revision 이력"
                />
                {selectedExecutionId ? (
                  <FeedbackForm
                    formId={FEEDBACK_FORM_ID}
                    orderPlanPk={orderPlanPk}
                    executionId={selectedExecutionId}
                    expectedRevision={expectedRevision}
                    onReadyChange={handleFeedbackReadyChange}
                    onSaved={() => setSavedMessage("사람 피드백 revision을 추가했습니다.")}
                  />
                ) : (
                  <p className="c2-muted">피드백을 기록할 execution history가 없습니다. 실행 기록 없이 revision을 만들지 않습니다.</p>
                )}
              </Panel>
            </div>

            <Panel title="screening execution history" className="c2-history-panel">
              {historyQuery.isError && detailQuery.data.screening_history.length === 0 ? <p className="c2-inline-warning" role="alert">screening history endpoint를 확인하지 못했습니다. 결과 없음과 실패를 구분할 수 없습니다.</p> : null}
              {history.length === 0 ? (
                <EmptyState compact title="screening execution history가 없습니다." description="실행 기록이 없으므로 단계 결과를 추정하지 않습니다." />
              ) : (
                <div className="c2-history-list">
                  {history.map((item, index) => (
                    <div key={`${item.execution_id}-${index}`}>
                      <button
                        type="button"
                        className={`c2-history-select ${selectedExecutionId === item.execution_id ? "is-selected" : ""}`.trim()}
                        aria-pressed={selectedExecutionId === item.execution_id}
                        onClick={() => setSelectedExecutionId(item.execution_id)}
                      >
                        <span className="mono">{item.execution_id}</span>
                        <StatusBadge label={item.execution_status} tone={statusTone(item.execution_status)} />
                        <span>source run {item.source_run_id}</span>
                      </button>
                      <ExecutionHistoryCard
                        item={item}
                        detail={executionDetails[index]?.data}
                        pending={executionDetails[index]?.isPending ?? false}
                        error={executionDetails[index]?.error}
                      />
                    </div>
                  ))}
                </div>
              )}
            </Panel>
          </div>

          {/* 우측 레일은 이력과 연결만 담는다(시안 주석 원문). 결정 액션은
              헤더에만 있고 여기서 복제하지 않는다. */}
          <ReviewHistoryLinkRail
            className="detail-skeleton-rail"
            footer={<p className="detail-skeleton-rail-note">우측 레일은 이력과 연결만 담습니다. 결정 액션은 헤더에만 있습니다.</p>}
            historySections={[
              {
                className: "detail-skeleton-rail-panel",
                empty: <EmptyState compact title="관측 history가 없습니다." description="서버가 제공한 관측 기록이 없어 변경 여부를 판단하지 않습니다." />,
                entries: detailQuery.data.observations.map((observation) => ({
                  detail: (
                    <span>
                      observed at {formatMoment(observation.observed_at)} · <ReviewValue className="c2-digest" value={observation.source_sha256} nullLabel="null (미제공)" />
                    </span>
                  ),
                  id: `${observation.source_run_id}-${observation.observed_at}`,
                  label: <span className="mono">source run {observation.source_run_id}</span>,
                })),
                label: "관측 history",
                listClassName: "detail-skeleton-rail-history",
              },
            ]}
            links={[{ href: returnPath, label: "발주계획 목록 →" }]}
            linksClassName="detail-skeleton-rail-links"
            title="이력과 연결"
          />
        </div>
      ) : null}
    </section>
  );
}
