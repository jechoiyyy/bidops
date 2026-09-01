import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router-dom";
import { EmptyState } from "../components/common/EmptyState";
import { Panel } from "../components/common/Panel";
import { StatusBadge, type StatusTone } from "../components/common/StatusBadge";
import { api, ApiError } from "../lib/api";
import type {
  OrderPlanListItem,
  OrderPlanListResponse,
  OrderPlanScreeningExecutionDetailResponse,
  OrderPlanScreeningExecutionListResponse,
  OrderPlanScreeningExecutionSummary,
} from "../lib/types";
import "../styles/order-plans.css";

type OrderPlanFilter = "review" | "all" | "bm25-filtered-out" | "qwen-not-relevant" | "failure";

const PAGE_SIZE = 500;
const FILTERS: Array<{ key: OrderPlanFilter; label: string; description: string }> = [
  { key: "review", label: "검토 대상", description: "Qwen relevant 또는 uncertain" },
  { key: "all", label: "전체", description: "최신 성공/부분 성공 결과 전체" },
  { key: "bm25-filtered-out", label: "BM25 탈락", description: "BM25 Top 범위 밖" },
  { key: "qwen-not-relevant", label: "Qwen 비관련", description: "Qwen not_relevant" },
  { key: "failure", label: "실패", description: "단계 실패 또는 거부" },
];

function isFilter(value: string | null): value is OrderPlanFilter {
  return FILTERS.some((filter) => filter.key === value);
}

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

function plannedTiming(year: string | null, month: string | null): string {
  if (year === null && month === null) return "null (계획 시기 미제공)";
  return `${year ?? "null"}년 ${month ?? "null"}월`;
}

function statusTone(status: string | null | undefined): StatusTone {
  if (status === "성공" || status === "relevant" || status === "selected") return "success";
  if (status === "부분 성공" || status === "uncertain" || status === "실행 중" || status === "중지 요청") return "warning";
  if (status === "실패" || status === "failed" || status === "rejected" || status === "not_relevant") return "danger";
  if (status === "대기" || status === "unknown" || status === "not_attempted") return "info";
  return "neutral";
}

function stage1Label(value: OrderPlanListItem["stage1_status"]): string {
  if (value === "filtered_out") return "BM25 탈락";
  if (value === "selected") return "BM25 선정";
  if (value === "failed") return "BM25 실패";
  if (value === "rejected") return "BM25 거부";
  return "BM25 결과 null";
}

function stage2Label(value: OrderPlanListItem["stage2_status"]): string {
  if (value === "not_attempted") return "Qwen 미시도";
  if (value === "success") return "Qwen 완료";
  if (value === "failed") return "Qwen 실패";
  if (value === "rejected") return "Qwen 거부";
  if (value === "unknown") return "Qwen unknown";
  return "Qwen 결과 null";
}

function latestCompletedExecution(items: OrderPlanScreeningExecutionSummary[]): OrderPlanScreeningExecutionSummary | null {
  return items
    .filter((item) => item.status === "성공" || item.status === "부분 성공")
    .reduce<OrderPlanScreeningExecutionSummary | null>((latest, item) => {
      if (!latest) return item;
      const latestAt = Date.parse(latest.finished_at ?? latest.queued_at);
      const itemAt = Date.parse(item.finished_at ?? item.queued_at);
      if (itemAt > latestAt || (itemAt === latestAt && item.execution_id > latest.execution_id)) return item;
      return latest;
    }, null);
}

async function fetchAllExecutions(signal: AbortSignal): Promise<OrderPlanScreeningExecutionListResponse> {
  const first = await api.getOrderPlanScreeningExecutions({ limit: PAGE_SIZE, offset: 0 }, { signal });
  const items = [...first.items];
  const pageSize = first.limit > 0 ? first.limit : PAGE_SIZE;
  while (items.length < first.total) {
    const page = await api.getOrderPlanScreeningExecutions({ limit: pageSize, offset: items.length }, { signal });
    if (!page.items.length) break;
    items.push(...page.items);
  }
  return { ...first, items, offset: 0 };
}

async function fetchAllOrderPlans(sourceRunId: string, queryText: string, signal: AbortSignal): Promise<OrderPlanListResponse> {
  const first = await api.getOrderPlans({
    source_run_id: sourceRunId,
    q: queryText || undefined,
    limit: PAGE_SIZE,
    offset: 0,
  }, { signal });
  const items = [...first.items];
  const pageSize = first.limit > 0 ? first.limit : PAGE_SIZE;
  while (items.length < first.total) {
    const page = await api.getOrderPlans({
      source_run_id: sourceRunId,
      q: queryText || undefined,
      limit: pageSize,
      offset: items.length,
    }, { signal });
    if (!page.items.length) break;
    items.push(...page.items);
  }
  return { ...first, items, offset: 0 };
}

function isFailure(item: OrderPlanListItem): boolean {
  return item.stage1_status === "failed"
    || item.stage1_status === "rejected"
    || item.stage2_status === "failed"
    || item.stage2_status === "rejected";
}

function ExecutionOverview({
  execution,
  detail,
  detailPending,
  detailError,
}: {
  execution: OrderPlanScreeningExecutionSummary;
  detail: OrderPlanScreeningExecutionDetailResponse | undefined;
  detailPending: boolean;
  detailError: unknown;
}) {
  const counts = execution.counts;
  return (
    <Panel className="c2-execution-panel" title="최신 성공/부분 성공 실행 계약">
      <div className="c2-execution-heading">
        <div>
          <p className="c2-kicker">source run</p>
          <p className="c2-execution-id mono">{execution.execution_id}</p>
          <p className="c2-muted">{formatMoment(execution.finished_at ?? execution.queued_at)}</p>
        </div>
        <div className="c2-status-cluster">
          <StatusBadge label={execution.status} tone={statusTone(execution.status)} />
          <span className="c2-status-text">{execution.execution_allowed ? "policy/binding 허용" : "policy/binding 비허용"}</span>
        </div>
      </div>

      <div className="c2-fact-grid">
        <div><dt>source run</dt><dd className="mono">{execution.source_run_id}</dd></div>
        <div><dt>요청자</dt><dd>{textOrUnknown(execution.requested_by)}</dd></div>
        <div><dt>policy version</dt><dd className="mono">{execution.policy_version}</dd></div>
        <div><dt>population</dt><dd>{formatNumber(execution.population_count)}건</dd></div>
        <div><dt>대상 hash</dt><dd className="c2-digest">{execution.population_sha256}</dd></div>
        <div><dt>policy hash</dt><dd className="c2-digest">{execution.policy_sha256}</dd></div>
        <div><dt>binding status</dt><dd>{execution.execution_allowed ? "허용됨" : "비허용됨"}</dd></div>
        <div><dt>binding hash</dt><dd className="c2-digest">{execution.binding_sha256}</dd></div>
      </div>

      <div className="c2-binding-grid" aria-label="단계별 binding">
        <div>
          <strong>BM25 binding</strong>
          <span className="mono">{execution.stage1_binding_version}</span>
          <span className="c2-digest">{execution.stage1_binding_sha256}</span>
        </div>
        <div>
          <strong>Qwen binding</strong>
          <span className="mono">{execution.stage2_binding_version}</span>
          <span className="c2-digest">{execution.stage2_binding_sha256}</span>
        </div>
      </div>

      <div className="c2-count-grid" aria-label="실행 집계">
        <div><span>후보</span><strong>{counts.candidate_count}</strong></div>
        <div><span>완료</span><strong>{counts.completed_count}</strong></div>
        <div><span>실패</span><strong>{counts.failure_count}</strong></div>
        <div><span>BM25 선정</span><strong>{counts.stage1_selected_count}</strong></div>
        <div><span>BM25 탈락</span><strong>{counts.stage1_filtered_out_count}</strong></div>
        <div><span>BM25 실패</span><strong>{counts.stage1_failed_count}</strong></div>
        <div><span>Qwen relevant</span><strong>{counts.stage2_relevant_count}</strong></div>
        <div><span>Qwen not relevant</span><strong>{counts.stage2_not_relevant_count}</strong></div>
        <div><span>Qwen uncertain</span><strong>{counts.stage2_uncertain_count}</strong></div>
        <div><span>Qwen 실패</span><strong>{counts.stage2_failed_count}</strong></div>
        <div><span>Qwen 거부</span><strong>{counts.stage2_rejected_count}</strong></div>
        <div><span>사람 검토</span><strong>{counts.human_review_count}</strong></div>
      </div>

      <div className="c2-contract-table">
        <h4>실행 model / revision / prompt / profile / attempt</h4>
        {detail?.attempts.length ? (
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
        ) : detail ? <p className="c2-muted">attempt 기록 없음 (서버 응답)</p> : null}
        <dl className="c2-fact-grid c2-fact-grid-compact">
          <div><dt>partial artifact</dt><dd>{execution.partial_artifact ? "있음" : "없음"}</dd></div>
          <div><dt>error code</dt><dd>{execution.error_code === null ? "null (서버 미제공)" : execution.error_code}</dd></div>
        </dl>
      </div>

      {detailPending ? <p className="c2-muted" role="status">실행 artifact 요약을 불러오는 중…</p> : null}
      {detailError ? (
        <p className="c2-inline-warning" role="alert">실행 상세를 불러오지 못해 artifact·attempt 안전 요약을 확인할 수 없습니다.</p>
      ) : null}
      {detail?.artifacts.length ? (
        <div className="c2-artifact-summary">
          <h4>안전한 artifact 요약</h4>
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
          <p className="c2-muted">본문·원문 경로·다운로드 URL은 이 화면에서 노출하지 않습니다.</p>
        </div>
      ) : null}
    </Panel>
  );
}

function ActiveExecutionNotice({ executions }: { executions: OrderPlanScreeningExecutionSummary[] }) {
  const active = executions.filter((item) => item.status === "대기" || item.status === "실행 중" || item.status === "중지 요청");
  if (!active.length) return null;
  return (
    <Panel className="c2-live-panel" title="현재 실행 상태" tone="warning">
      <ul className="c2-live-list">
        {active.map((execution) => (
          <li key={execution.execution_id}>
            <StatusBadge label={execution.status} tone={statusTone(execution.status)} />
            <span className="mono">{execution.execution_id}</span>
            <span>heartbeat {formatMoment(execution.heartbeat_at)}</span>
          </li>
        ))}
      </ul>
      <p className="c2-inline-warning">
        서버 계약은 stale 여부를 별도 판정하지 않습니다. 중지 요청·프로세스 중단 뒤 자동 재개하지 않으며, 실시간 실행은 이 화면의 검토 결과와 분리합니다.
      </p>
    </Panel>
  );
}

function PlanCard({ item, returnSearch }: { item: OrderPlanListItem; returnSearch: string }) {
  const detailPath = `/order-plans/${item.order_plan_pk}${returnSearch ? `?${returnSearch}` : ""}`;
  const feedback = item.human_feedback;
  return (
    <article className="c2-plan-card">
      <div className="c2-plan-card-header">
        <div>
          <p className="c2-card-eyebrow">발주계획 {item.order_plan_unty_no}</p>
          <h3><Link to={detailPath}>{textOrUnknown(item.title)}</Link></h3>
        </div>
        <div className="c2-status-cluster">
          <StatusBadge label={stage1Label(item.stage1_status)} tone={statusTone(item.stage1_status)} />
          <StatusBadge label={stage2Label(item.stage2_status)} tone={statusTone(item.stage2_status)} />
        </div>
      </div>

      <dl className="c2-plan-facts">
        <div><dt>기관</dt><dd>{textOrUnknown(item.agency_name)}</dd></div>
        <div><dt>사업 분야</dt><dd>{textOrUnknown(item.business_division)}</dd></div>
        <div><dt>계획 ID</dt><dd className="mono">{item.order_plan_pk}</dd></div>
        <div><dt>source run</dt><dd className="mono">{textOrUnknown(item.source_run_id)}</dd></div>
        <div><dt>관측 시각</dt><dd>{formatMoment(item.observed_at)}</dd></div>
        <div><dt>예산</dt><dd>{item.budget_amount === null ? "null (미제공)" : item.budget_amount.toLocaleString("ko-KR")}</dd></div>
        <div><dt>계획 시기</dt><dd>{plannedTiming(item.planned_order_year, item.planned_order_month)}</dd></div>
      </dl>

      <div className="c2-signal-grid">
        <section className="c2-signal c2-signal-bm25" aria-labelledby={`bm25-${item.order_plan_pk}`}>
          <h4 id={`bm25-${item.order_plan_pk}`}>BM25 후보 신호</h4>
          <dl>
            <div><dt>rank</dt><dd>{item.stage1_rank === null ? "null (값 없음/미측정)" : item.stage1_rank}</dd></div>
            <div><dt>score</dt><dd>{formatScore(item.stage1_score)}</dd></div>
            <div><dt>nearest capability</dt><dd>{item.nearest_capability ?? "null (미제공)"}</dd></div>
          </dl>
        </section>
        <section className="c2-signal c2-signal-qwen" aria-labelledby={`qwen-${item.order_plan_pk}`}>
          <h4 id={`qwen-${item.order_plan_pk}`}>Qwen relevance 신호</h4>
          <dl>
            <div><dt>relevance</dt><dd>{item.qwen_relevance ?? "null (값 없음/미적용)"}</dd></div>
            <div><dt>score</dt><dd>{formatScore(item.qwen_score)}</dd></div>
            <div><dt>reason</dt><dd>{item.qwen_reason ?? "null (근거 미제공)"}</dd></div>
          </dl>
        </section>
      </div>

      <div className="c2-plan-card-footer">
        <p>
          사람 피드백: {feedback ? `revision ${feedback.revision} · ${feedback.relevance} · ${feedback.priority ?? "priority null"}` : "없음"}
        </p>
        <Link className="c2-text-link" to={detailPath}>관측·실행·피드백 상세 보기 →</Link>
      </div>
    </article>
  );
}

function ExecutionMissingState({ executions }: { executions: OrderPlanScreeningExecutionSummary[] }) {
  if (!executions.length) {
    return (
      <EmptyState
        title="C-2 실행 결과가 없습니다."
        description="성공 또는 부분 성공 실행이 없어 발주계획을 표시하지 않습니다. 결과 없음은 비관련로 해석하지 않습니다."
      />
    );
  }
  return (
    <EmptyState
      tone="warning"
      title="검토에 사용할 성공/부분 성공 결과가 없습니다."
      description={`최근 실행 상태: ${executions.slice(0, 3).map((item) => `${item.status} (${item.execution_id})`).join(", ")}. 실패·중단·중지 상태를 성공 결과로 해석하지 않습니다.`}
    />
  );
}

export function OrderPlansPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const filter = isFilter(searchParams.get("filter")) ? searchParams.get("filter") as OrderPlanFilter : "review";
  const queryText = searchParams.get("q") ?? "";
  const offsetValue = Number(searchParams.get("offset") ?? "0");
  const offset = Number.isFinite(offsetValue) && offsetValue >= 0 ? Math.floor(offsetValue / PAGE_SIZE) * PAGE_SIZE : 0;
  const [searchValue, setSearchValue] = useState(queryText);

  useEffect(() => setSearchValue(queryText), [queryText]);

  const executionsQuery = useQuery({
    queryKey: ["order-plan-c2", "executions"],
    queryFn: ({ signal }) => fetchAllExecutions(signal),
    staleTime: 15_000,
  });
  const executions = executionsQuery.data?.items ?? [];
  const latestExecution = useMemo(() => latestCompletedExecution(executions), [executions]);

  const listQuery = useQuery({
    queryKey: ["order-plan-c2", "list", latestExecution?.source_run_id, queryText],
    queryFn: ({ signal }) => fetchAllOrderPlans(latestExecution?.source_run_id as string, queryText, signal),
    enabled: Boolean(latestExecution?.source_run_id),
    staleTime: 15_000,
  });

  const executionDetailQuery = useQuery({
    queryKey: ["order-plan-c2", "execution-detail", latestExecution?.execution_id],
    queryFn: ({ signal }) => api.getOrderPlanScreeningExecution(latestExecution?.execution_id as string, { signal }),
    enabled: Boolean(latestExecution?.execution_id),
    staleTime: 15_000,
  });

  const filteredItems = useMemo(() => {
    const items = listQuery.data?.items ?? [];
    if (filter === "review") return items.filter((item) => item.qwen_relevance === "relevant" || item.qwen_relevance === "uncertain");
    if (filter === "failure") return items.filter(isFailure);
    if (filter === "bm25-filtered-out") return items.filter((item) => item.stage1_status === "filtered_out");
    if (filter === "qwen-not-relevant") return items.filter((item) => item.qwen_relevance === "not_relevant");
    return items;
  }, [filter, listQuery.data?.items]);
  const visibleItems = useMemo(() => filteredItems.slice(offset, offset + PAGE_SIZE), [filteredItems, offset]);

  const updateListParams = (updates: { filter?: OrderPlanFilter; q?: string; offset?: number }) => {
    const next = new URLSearchParams(searchParams);
    if (updates.filter && updates.filter !== "review") next.set("filter", updates.filter);
    else if (updates.filter) next.delete("filter");
    if (updates.q !== undefined) {
      if (updates.q.trim()) next.set("q", updates.q.trim());
      else next.delete("q");
    }
    if (updates.offset) next.set("offset", String(updates.offset));
    else if (updates.offset === 0) next.delete("offset");
    setSearchParams(next, { replace: true });
  };

  const listError = listQuery.error instanceof ApiError ? listQuery.error.message : "발주계획 목록을 확인할 수 없습니다.";
  const executionError = executionsQuery.error instanceof ApiError ? executionsQuery.error.message : "C-2 실행 목록을 확인할 수 없습니다.";
  const total = filteredItems.length;
  const hasPrevious = offset > 0;
  const hasNext = offset + visibleItems.length < total;

  return (
    <section className="c2-page" aria-labelledby="order-plans-title">
      <header className="c2-page-header">
        <div>
          <p className="c2-kicker">모니터링 · 발주계획 C-2</p>
          <h2 id="order-plans-title">발주계획 C-2 검토</h2>
          <p className="c2-page-lede">
            BM25 후보 신호와 Qwen relevance 신호를 분리해 최신 성공/부분 성공 실행을 검토합니다. 이 relevance는 tracking state, fitness grade, readiness, 최종 Go/No-Go가 아닙니다.
          </p>
          <p className="c2-semantics-note"><code>filtered_out</code>는 BM25 탈락, <code>not_relevant</code>는 Qwen relevance, <code>unknown</code>은 정보 부족, <code>null</code>은 값 없음/미적용이며 서로 바꾸지 않습니다.</p>
        </div>
        <div className="c2-contract-note">API 계약 기반 · 미제공 값은 추정하지 않음</div>
      </header>

      {executionsQuery.isPending ? <p className="c2-loading" role="status">C-2 실행 목록을 불러오는 중…</p> : null}
      {executionsQuery.isError ? (
        <EmptyState tone="error" title="C-2 실행 목록을 불러오지 못했습니다." description={executionError} action={{ label: "다시 시도", onClick: () => void executionsQuery.refetch() }} />
      ) : null}
      {!executionsQuery.isPending && !executionsQuery.isError ? (
        <>
          <ActiveExecutionNotice executions={executions} />
          {latestExecution ? (
            <ExecutionOverview
              execution={latestExecution}
              detail={executionDetailQuery.data}
              detailPending={executionDetailQuery.isPending}
              detailError={executionDetailQuery.error}
            />
          ) : <ExecutionMissingState executions={executions} />}
        </>
      ) : null}

      {latestExecution ? (
        <section className="c2-results" aria-labelledby="c2-results-title">
          <div className="c2-results-heading">
            <div>
              <p className="c2-kicker">{latestExecution.source_run_id}</p>
              <h3 id="c2-results-title">검토 목록</h3>
              <p className="c2-muted">기준 실행: {latestExecution.execution_id} · 현재 필터 결과 {total.toLocaleString("ko-KR")}건 중 현재 페이지 {visibleItems.length.toLocaleString("ko-KR")}건</p>
            </div>
            <form className="c2-search-form" onSubmit={(event) => { event.preventDefault(); updateListParams({ q: searchValue, offset: 0 }); }}>
              <label htmlFor="order-plan-search">제목·계획번호 검색</label>
              <div>
                <input id="order-plan-search" value={searchValue} onChange={(event) => setSearchValue(event.target.value)} placeholder="검색어" />
                <button type="submit" className="c2-button">검색</button>
              </div>
            </form>
          </div>

          <div className="c2-filter-bar" role="group" aria-label="C-2 결과 필터">
            {FILTERS.map((item) => (
              <button
                key={item.key}
                type="button"
                aria-pressed={filter === item.key}
                className={`c2-filter ${filter === item.key ? "is-active" : ""}`.trim()}
                onClick={() => updateListParams({ filter: item.key, offset: 0 })}
              >
                <span>{item.label}</span>
                <small>{item.description}</small>
              </button>
            ))}
          </div>

          {listQuery.isPending ? <p className="c2-loading" role="status">발주계획을 불러오는 중…</p> : null}
          {listQuery.isError ? <EmptyState tone="error" title="발주계획 목록을 불러오지 못했습니다." description={listError} action={{ label: "다시 시도", onClick: () => void listQuery.refetch() }} /> : null}
          {!listQuery.isPending && !listQuery.isError && visibleItems.length === 0 ? (
            <EmptyState
              title="현재 필터에 해당하는 결과가 없습니다."
              description="표시되지 않은 값이나 실행 실패를 다른 relevance 상태로 바꾸지 않습니다. 필터와 source run을 확인하십시오."
            />
          ) : null}
          {!listQuery.isPending && !listQuery.isError && visibleItems.length > 0 ? (
            <div className="c2-plan-list">
              {visibleItems.map((item) => <PlanCard key={item.order_plan_pk} item={item} returnSearch={searchParams.toString()} />)}
            </div>
          ) : null}

          {listQuery.data && (hasPrevious || hasNext) ? (
            <nav className="c2-pagination" aria-label="발주계획 목록 페이지">
              <button type="button" className="c2-button c2-button-secondary" disabled={!hasPrevious} onClick={() => updateListParams({ offset: Math.max(0, offset - PAGE_SIZE) })}>이전</button>
              <span>{(offset + 1).toLocaleString("ko-KR")}–{Math.min(offset + visibleItems.length, total).toLocaleString("ko-KR")} / {total.toLocaleString("ko-KR")}</span>
              <button type="button" className="c2-button c2-button-secondary" disabled={!hasNext} onClick={() => updateListParams({ offset: offset + PAGE_SIZE })}>다음</button>
            </nav>
          ) : null}
        </section>
      ) : null}
    </section>
  );
}
