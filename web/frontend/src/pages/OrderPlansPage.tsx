import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router-dom";
import { Badge } from "@astryxdesign/core/Badge";
import { Banner } from "@astryxdesign/core/Banner";
import { Button } from "@astryxdesign/core/Button";
import { Collapsible } from "@astryxdesign/core/Collapsible";
import { Heading } from "@astryxdesign/core/Heading";
import { SegmentedControl, SegmentedControlItem } from "@astryxdesign/core/SegmentedControl";
import { Stack } from "@astryxdesign/core/Stack";
import { StatusDot } from "@astryxdesign/core/StatusDot";
import { Tab, TabList } from "@astryxdesign/core/TabList";
import { TextArea } from "@astryxdesign/core/TextArea";
import { TextInput } from "@astryxdesign/core/TextInput";
import { ToggleButton, ToggleButtonGroup } from "@astryxdesign/core/ToggleButton";
import { Text } from "@astryxdesign/core/Text";
import {
  DenseList,
  DenseListRow,
  ReviewDecisionAction,
  ReviewDecisionBar,
  ReviewFilterBar,
  ReviewFilterSegmentedControl,
  ReviewFilterSelector,
  ReviewFilterTextInput,
  ReviewSecondaryInput,
  ReviewState,
  ReviewStatus,
  ReviewValue,
  SplitWorkspace,
  StickyDecisionHeader,
} from "../components/common/ReviewPrimitives";
import { api, ApiError } from "../lib/api";
import type {
  OrderPlanFeedbackPriority,
  OrderPlanListItem,
  OrderPlanListResponse,
  OrderPlanRelevance,
  OrderPlanScreeningExecutionDetailResponse,
  OrderPlanScreeningExecutionListResponse,
  OrderPlanScreeningExecutionSummary,
  OrderPlanStage1Status,
  OrderPlanStage2Status,
  OrderPlanTrackingDecisionStatus,
} from "../lib/types";
import "../styles/order-plans.css";

const PAGE_SIZE = 500;
const MIN_LIST_WIDTH = 300;
const MAX_LIST_WIDTH = 640;
const DEFAULT_LIST_WIDTH = 380;
const LIST_WIDTH_STEP = 24;
const LIST_WIDTH_STORAGE_KEY = "bidops.order-plans.listWidth";
const SAVED_VIEWS_STORAGE_KEY = "bidops.order-plans.views";

type RelevanceToken = "relevant" | "uncertain" | "not_relevant" | "null";
type Stage1Token = "selected" | "filtered_out" | "failed" | "rejected" | "null";
type FeedbackToken = "has" | "none";
type DetailTab = "verdict" | "signals" | "telemetry";

const RELEVANCE_TOKENS: readonly RelevanceToken[] = ["relevant", "uncertain", "not_relevant", "null"];
const STAGE1_TOKENS: readonly Stage1Token[] = ["selected", "filtered_out", "failed", "rejected", "null"];
const FEEDBACK_TOKENS: readonly FeedbackToken[] = ["has", "none"];
const AXIS_KEYS = ["qwen", "stage1", "feedback", "issue", "q"] as const;

interface FilterAxes {
  qwen: RelevanceToken[];
  stage1: Stage1Token[];
  feedback: FeedbackToken[];
  issue: boolean;
}

interface Preset {
  key: string;
  label: string;
  description: string;
  axes: FilterAxes;
}

const PRESETS: Preset[] = [
  { key: "review", label: "검토 대상", description: "Qwen relevant 또는 uncertain", axes: { qwen: ["relevant", "uncertain"], stage1: [], feedback: [], issue: false } },
  { key: "all", label: "전체", description: "최신 성공/부분 성공 결과 전체", axes: { qwen: [], stage1: [], feedback: [], issue: false } },
  { key: "bm25-filtered-out", label: "BM25 탈락", description: "BM25 Top 범위 밖", axes: { qwen: [], stage1: ["filtered_out"], feedback: [], issue: false } },
  { key: "failure", label: "실패·거부", description: "BM25 또는 Qwen 단계 실패·거부", axes: { qwen: [], stage1: [], feedback: [], issue: true } },
];

interface SavedView {
  id: string;
  name: string;
  search: string;
  createdAt: string;
}

function requestId(): string {
  if (typeof globalThis.crypto?.randomUUID === "function") return globalThis.crypto.randomUUID();
  throw new Error("브라우저가 계약에 필요한 UUID 생성을 지원하지 않습니다.");
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

function budgetLabel(value: number | null): string {
  return value === null ? "예산 null (미제공)" : `예산 ${value.toLocaleString("ko-KR")}`;
}

function stage1RowLabel(value: OrderPlanStage1Status | null): string {
  if (value === "selected") return "BM25 선정";
  if (value === "filtered_out") return "BM25 탈락";
  if (value === "failed") return "BM25 실패";
  if (value === "rejected") return "BM25 거부";
  return "BM25 결과 null";
}

function stage1BadgeVariant(value: OrderPlanStage1Status | null): "success" | "neutral" | "error" {
  if (value === "selected") return "success";
  if (value === "failed" || value === "rejected") return "error";
  return "neutral";
}

/** stage2_status 5값(not_attempted/success/failed/rejected/unknown)을 그대로 구분한다.
 * relevance가 null이라고 실패·거부·미시도·unknown을 전부 같은 문구로 뭉개지 않는다. */
function stage2Label(value: OrderPlanStage2Status | null): string {
  if (value === "not_attempted") return "Qwen 미시도";
  if (value === "success") return "Qwen 완료";
  if (value === "failed") return "Qwen 실패";
  if (value === "rejected") return "Qwen 거부";
  if (value === "unknown") return "Qwen unknown";
  return "Qwen 결과 null";
}

/** relevance가 있으면 relevance 문구를, 없으면(null) stage2_status로 이유를 구분해 보여준다.
 * qwen_relevance만 보면 not_attempted·failed·rejected·unknown이 전부 "null"로 뭉개지므로
 * (F1) 행과 신호 세부 탭 양쪽에서 이 함수 하나로 일관되게 표시한다. */
function qwenRowLabel(item: { qwen_relevance: OrderPlanRelevance | null; stage2_status: OrderPlanStage2Status | null }): string {
  if (item.qwen_relevance === "relevant") return "relevant";
  if (item.qwen_relevance === "uncertain") return "uncertain";
  if (item.qwen_relevance === "not_relevant") return "not_relevant";
  return stage2Label(item.stage2_status);
}

function qwenBadgeVariant(item: { qwen_relevance: OrderPlanRelevance | null; stage2_status: OrderPlanStage2Status | null }): "success" | "warning" | "error" | "neutral" {
  if (item.qwen_relevance === "relevant") return "success";
  if (item.qwen_relevance === "uncertain") return "warning";
  if (item.qwen_relevance === "not_relevant") return "neutral";
  if (item.stage2_status === "failed" || item.stage2_status === "rejected") return "error";
  return "neutral";
}

function relevanceToken(value: OrderPlanRelevance | null): RelevanceToken {
  return (value ?? "null") as RelevanceToken;
}

function stage1Token(value: OrderPlanStage1Status | null): Stage1Token {
  return (value ?? "null") as Stage1Token;
}

function isExecutionIssue(item: OrderPlanListItem): boolean {
  const stage1Bad = item.stage1_status === "failed" || item.stage1_status === "rejected";
  const stage2Bad = item.stage2_status === "failed" || item.stage2_status === "rejected";
  return stage1Bad || stage2Bad;
}

function statusTone(status: string | null | undefined): "success" | "warning" | "error" | "info" | "neutral" {
  if (status === "성공" || status === "relevant" || status === "selected") return "success";
  if (status === "부분 성공" || status === "uncertain" || status === "실행 중" || status === "중지 요청") return "warning";
  if (status === "실패" || status === "failed" || status === "rejected" || status === "not_relevant") return "error";
  if (status === "대기" || status === "unknown" || status === "not_attempted") return "info";
  return "neutral";
}

/** StatusDot은 success/warning/error/accent/neutral만 지원한다(Badge와 다름). */
function statusDotVariant(status: string | null | undefined): "success" | "warning" | "error" | "accent" | "neutral" {
  const tone = statusTone(status);
  return tone === "info" ? "accent" : tone;
}

function parseTokenSet<T extends string>(raw: string | null, allowed: readonly T[]): Set<T> {
  const set = new Set<T>();
  if (!raw) return set;
  for (const part of raw.split(",")) {
    const trimmed = part.trim();
    if ((allowed as readonly string[]).includes(trimmed)) set.add(trimmed as T);
  }
  return set;
}

function serializeTokens(values: Iterable<string>): string {
  return Array.from(values).join(",");
}

function setEqualsArray<T>(set: Set<T>, values: readonly T[]): boolean {
  return set.size === values.length && values.every((value) => set.has(value));
}

function loadListWidth(): number {
  try {
    const raw = window.localStorage.getItem(LIST_WIDTH_STORAGE_KEY);
    const parsed = raw ? Number(raw) : NaN;
    if (!Number.isFinite(parsed)) return DEFAULT_LIST_WIDTH;
    return Math.min(MAX_LIST_WIDTH, Math.max(MIN_LIST_WIDTH, parsed));
  } catch {
    return DEFAULT_LIST_WIDTH;
  }
}

function saveListWidth(width: number): void {
  try {
    window.localStorage.setItem(LIST_WIDTH_STORAGE_KEY, String(width));
  } catch {
    /* localStorage 접근 불가는 화면 동작을 막지 않는다 */
  }
}

function loadSavedViews(): SavedView[] {
  try {
    const raw = window.localStorage.getItem(SAVED_VIEWS_STORAGE_KEY);
    if (!raw) return [];
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter((item): item is SavedView =>
      Boolean(item) && typeof (item as SavedView).id === "string" && typeof (item as SavedView).name === "string" && typeof (item as SavedView).search === "string");
  } catch {
    return [];
  }
}

function persistSavedViews(views: SavedView[]): void {
  try {
    window.localStorage.setItem(SAVED_VIEWS_STORAGE_KEY, JSON.stringify(views));
  } catch {
    /* localStorage 접근 불가는 화면 동작을 막지 않는다 */
  }
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

async function fetchAllOrderPlans(sourceRunId: string, signal: AbortSignal): Promise<OrderPlanListResponse> {
  const first = await api.getOrderPlans({ source_run_id: sourceRunId, limit: PAGE_SIZE, offset: 0 }, { signal });
  const items = [...first.items];
  const pageSize = first.limit > 0 ? first.limit : PAGE_SIZE;
  while (items.length < first.total) {
    const page = await api.getOrderPlans({ source_run_id: sourceRunId, limit: pageSize, offset: items.length }, { signal });
    if (!page.items.length) break;
    items.push(...page.items);
  }
  return { ...first, items, offset: 0 };
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

function executionHasProblem(latest: OrderPlanScreeningExecutionSummary | null, executions: OrderPlanScreeningExecutionSummary[]): boolean {
  if (!latest) return true;
  if (latest.status !== "성공") return true;
  if (!latest.execution_allowed) return true;
  return executions.some((item) => item.status === "대기" || item.status === "실행 중" || item.status === "중지 요청");
}

/** 실행 결과가 없거나 성공/부분 성공이 없을 때의 안내. 값 없음과 실패를 성공으로 바꾸지 않는다. */
function ExecutionMissingBlock({ executions }: { executions: OrderPlanScreeningExecutionSummary[] }) {
  if (!executions.length) {
    return <ReviewState
      kind="empty"
      title="C-2 실행 결과가 없습니다."
      description="성공 또는 부분 성공 실행이 없어 발주계획을 표시하지 않습니다. 결과 없음은 비관련로 해석하지 않습니다."
    />;
  }
  return (
    <ReviewState
      className="c2l-execution-empty"
      kind="failure"
      title="검토에 사용할 성공/부분 성공 결과가 없습니다."
      description={`실행 상태: ${executions.slice(0, 3).map((item) => `${item.status} (${item.execution_id})`).join(", ")}. 실패·중단·중지 상태를 성공 결과로 해석하지 않습니다.`}
    />
  );
}

function ExecutionSummaryLine({ latest, executions }: { latest: OrderPlanScreeningExecutionSummary | null; executions: OrderPlanScreeningExecutionSummary[] }) {
  const active = executions.filter((item) => item.status === "대기" || item.status === "실행 중" || item.status === "중지 요청");
  if (!latest) {
    return (
      <Stack direction="horizontal" gap={2} align="center">
        <ReviewStatus
          label="실행 없음"
          variant="neutral"
          detail="표시할 성공/부분 성공 실행이 없습니다."
        />
      </Stack>
    );
  }
  return (
    <Stack direction="horizontal" gap={2} align="center" wrap="wrap">
      <ReviewStatus
        label={latest.status}
        variant={statusDotVariant(latest.status)}
        detail={`· ${latest.execution_id.slice(0, 8)} · ${formatMoment(latest.finished_at ?? latest.queued_at)}`}
      />
      {!latest.execution_allowed ? <Badge variant="error" label="policy/binding 비허용" /> : null}
      {active.length ? <Badge variant="warning" label={`진행 중 실행 ${active.length}건`} /> : null}
    </Stack>
  );
}

/** BM25 rank/score/nearest capability와 Qwen score/reason. 목록 행에서 뺀 신호 세부다. */
function SignalPanel({ item }: { item: OrderPlanListItem }) {
  return (
    <div className="c2l-verdict">
      {/* source run·관측 시각은 판정 탭에서 뺐지만(시안 주석) 삭제하지 않고 이 탭에 남긴다(F3). */}
      <dl className="c2l-signal-facts">
        <div><dt>source run</dt><dd className="c2l-digest"><ReviewValue value={item.source_run_id} nullLabel="null (미제공)" /></dd></div>
        <div><dt>관측 시각</dt><dd>{formatMoment(item.observed_at)}</dd></div>
      </dl>
      <div className="c2l-signal-grid">
        <section className="c2l-signal" aria-labelledby={`c2l-bm25-${item.order_plan_pk}`}>
          <Heading level={5} id={`c2l-bm25-${item.order_plan_pk}`}>BM25 후보 신호</Heading>
          <dl className="c2l-signal-facts">
            <div><dt>status</dt><dd>{stage1RowLabel(item.stage1_status)}</dd></div>
            <div><dt>rank</dt><dd>{item.stage1_rank === null ? "null (값 없음/미측정)" : item.stage1_rank}</dd></div>
            <div><dt>score</dt><dd>{formatScore(item.stage1_score)}</dd></div>
            <div><dt>nearest capability</dt><dd><ReviewValue value={item.nearest_capability} nullLabel="null (미제공)" /></dd></div>
          </dl>
        </section>
        <section className="c2l-signal" aria-labelledby={`c2l-qwen-${item.order_plan_pk}`}>
          <Heading level={5} id={`c2l-qwen-${item.order_plan_pk}`}>Qwen relevance 신호</Heading>
          <dl className="c2l-signal-facts">
            {/* status(stage2_status)는 relevance와 별도 축이다: not_attempted·failed·rejected·unknown을
                relevance null 하나로 뭉개지 않는다(F1). */}
            <div><dt>status</dt><dd>{stage2Label(item.stage2_status)}</dd></div>
            <div><dt>relevance</dt><dd>{item.qwen_relevance ?? "null (값 없음/미적용)"}</dd></div>
            <div><dt>score</dt><dd>{formatScore(item.qwen_score)}</dd></div>
            <div><dt>reason</dt><dd><ReviewValue value={item.qwen_reason} nullLabel="null (근거 미제공)" /></dd></div>
          </dl>
        </section>
      </div>
    </div>
  );
}

/** model_digest·token 수·duration_ms·binding sha256·artifact 요약. 삭제하지 않고 이 탭으로 옮겼다. */
function TelemetryPanel({
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
    <div className="c2l-telemetry">
      <div className="c2l-telemetry-heading">
        <div>
          <Text type="supporting" color="secondary" as="p">source run</Text>
          <Text type="body" color="primary" as="p">{execution.source_run_id}</Text>
          <Text type="supporting" color="secondary" as="p">{formatMoment(execution.finished_at ?? execution.queued_at)}</Text>
        </div>
        <Stack direction="horizontal" gap={2} align="center">
          <Badge variant={statusTone(execution.status) === "error" ? "error" : statusTone(execution.status) === "warning" ? "warning" : "neutral"} label={execution.status} />
          <Text type="body" color="secondary">{execution.execution_allowed ? "policy/binding 허용" : "policy/binding 비허용"}</Text>
        </Stack>
      </div>

      <dl className="c2l-fact-grid">
        <div><dt>execution_id</dt><dd className="c2l-digest">{execution.execution_id}</dd></div>
        <div><dt>요청자</dt><dd>{textOrUnknown(execution.requested_by)}</dd></div>
        <div><dt>policy version</dt><dd>{execution.policy_version}</dd></div>
        <div><dt>population</dt><dd>{formatNumber(execution.population_count)}건</dd></div>
        <div><dt>대상 hash</dt><dd className="c2l-digest">{execution.population_sha256}</dd></div>
        <div><dt>policy hash</dt><dd className="c2l-digest">{execution.policy_sha256}</dd></div>
        <div><dt>binding status</dt><dd>{execution.execution_allowed ? "허용됨" : "허용됨이 아님"}</dd></div>
        <div><dt>binding hash</dt><dd className="c2l-digest">{execution.binding_sha256}</dd></div>
      </dl>

      <dl className="c2l-fact-grid" aria-label="단계별 binding">
        <div><dt>BM25 binding</dt><dd>{execution.stage1_binding_version} · <span className="c2l-digest">{execution.stage1_binding_sha256}</span></dd></div>
        <div><dt>Qwen binding</dt><dd>{execution.stage2_binding_version} · <span className="c2l-digest">{execution.stage2_binding_sha256}</span></dd></div>
      </dl>

      <dl className="c2l-count-grid" aria-label="실행 집계">
        <div><dt>후보</dt><dd>{counts.candidate_count}</dd></div>
        <div><dt>완료</dt><dd>{counts.completed_count}</dd></div>
        <div><dt>실패</dt><dd>{counts.failure_count}</dd></div>
        <div><dt>BM25 선정</dt><dd>{counts.stage1_selected_count}</dd></div>
        <div><dt>BM25 탈락</dt><dd>{counts.stage1_filtered_out_count}</dd></div>
        <div><dt>BM25 실패</dt><dd>{counts.stage1_failed_count}</dd></div>
        <div><dt>Qwen relevant</dt><dd>{counts.stage2_relevant_count}</dd></div>
        <div><dt>Qwen not relevant</dt><dd>{counts.stage2_not_relevant_count}</dd></div>
        <div><dt>Qwen uncertain</dt><dd>{counts.stage2_uncertain_count}</dd></div>
        <div><dt>Qwen 실패</dt><dd>{counts.stage2_failed_count}</dd></div>
        <div><dt>Qwen 거부</dt><dd>{counts.stage2_rejected_count}</dd></div>
        <div><dt>사람 검토</dt><dd>{counts.human_review_count}</dd></div>
      </dl>

      <div className="c2l-telemetry-attempts">
        <Heading level={5}>실행 model / revision / prompt / profile / attempt</Heading>
        {detailPending ? <Text type="body" color="secondary" as="p">실행 artifact 요약을 불러오는 중…</Text> : null}
        {detailError ? <Text type="body" color="secondary" as="p" data-role="alert">실행 상세를 불러오지 못해 artifact·attempt 안전 요약을 확인할 수 없습니다.</Text> : null}
        {detail?.attempts.length ? (
          <ol className="c2l-attempt-list">
            {detail.attempts.map((attempt) => (
              <li key={attempt.attempt_id}>
                <Text type="body" color="primary" weight="semibold" as="p">batch {attempt.batch_id} · attempt {attempt.attempt_no}</Text>
                <dl className="c2l-attempt-grid">
                  <div><dt>model / revision</dt><dd>{attempt.model_name} · <span className="c2l-digest">{attempt.model_digest}</span></dd></div>
                  <div><dt>prompt</dt><dd>{attempt.prompt_version} · <span className="c2l-digest">{attempt.prompt_sha256}</span></dd></div>
                  <div><dt>profile</dt><dd>{attempt.company_profile_version} · <span className="c2l-digest">{attempt.company_profile_sha256}</span></dd></div>
                  <div><dt>generation config</dt><dd className="c2l-digest">{attempt.generation_config_sha256}</dd></div>
                  <div><dt>status</dt><dd><Badge variant={attempt.attempt_status === "success" ? "success" : attempt.attempt_status === "running" ? "warning" : "error"} label={attempt.attempt_status} /></dd></div>
                  <div><dt>failure</dt><dd>{attempt.failure_type ?? "null"} · {attempt.failure_code ?? "null"}</dd></div>
                  <div><dt>tokens (input / cached / output / total)</dt><dd>{formatNumber(attempt.input_tokens)} / {formatNumber(attempt.cached_input_tokens)} / {formatNumber(attempt.output_tokens)} / {formatNumber(attempt.total_tokens)}</dd></div>
                  <div><dt>duration_ms</dt><dd>{formatNumber(attempt.duration_ms)}</dd></div>
                  <div><dt>시각</dt><dd>{formatNullableMoment(attempt.started_at)} → {formatNullableMoment(attempt.finished_at)}</dd></div>
                </dl>
              </li>
            ))}
          </ol>
        ) : detail ? <Text type="body" color="secondary" as="p">attempt 기록 없음 (서버 응답)</Text> : null}
        <dl className="c2l-fact-grid">
          <div><dt>partial artifact</dt><dd>{execution.partial_artifact ? "있음" : "없음"}</dd></div>
          <div><dt>error code</dt><dd>{execution.error_code === null ? "null (서버 미제공)" : execution.error_code}</dd></div>
        </dl>
      </div>

      {detail?.artifacts.length ? (
        <div className="c2l-artifact-summary">
          <Heading level={5}>안전한 artifact 요약</Heading>
          <ul>
            {detail.artifacts.map((artifact) => (
              <li key={`${artifact.kind}-${artifact.sha256}`}>
                <span>{artifact.kind}</span>
                <Badge variant={artifact.validation_status === "valid" ? "success" : artifact.validation_status === "invalid" ? "error" : "warning"} label={artifact.validation_status} />
                <span>{artifact.byte_count.toLocaleString("ko-KR")} bytes</span>
                <span className="c2l-digest">{artifact.sha256}</span>
              </li>
            ))}
          </ul>
          <Text type="supporting" color="secondary" as="p">본문·원문 경로·다운로드 URL은 이 화면에서 노출하지 않습니다.</Text>
        </div>
      ) : null}
    </div>
  );
}

/**
 * 추적 결정(결정 1)의 사유 선택지.
 *
 * 요청안 §8 Q5가 "사유를 자유 문자열로 둘 것인가, 계약이 집합을 고정할 것인가"를 묻고 있다.
 * 계약이 자유 문자열로 확정되면 이 목록은 추천값이 되고, 집합을 고정하면 계약이 정본이 된다.
 * 어느 쪽이든 화면이 사유를 만들어 내지 않도록 한곳에 모아 둔다.
 */
const TRACKING_REASONS = [
  "후속 사전규격·공고 확인",
  "회사 역량과 맞음",
  "예산·시기 추가 확인 필요",
  "역량 밖으로 판단",
  "중복·오탐으로 확인",
] as const;

/**
 * 추적 결정을 기록할 수 있는지의 세 상태. 서로 바꾸지 않는다.
 *
 * - `contract_missing`: 응답에 `tracking`이 없다. 서버 계약이 아직 없다는 뜻이며
 *   `미선택`이 아니다 (요청안 §7 규칙 3).
 * - `opportunity_missing`: `tracking`이 `null`이다. 이 발주계획을 소유한 사업기회를
 *   확인하지 못했다.
 * - `available`: 추적 상태를 읽었다. 그 값이 `미선택`일 수 있고, 미선택은 종료가 아니다.
 */
type TrackingAvailability = "available" | "contract_missing" | "opportunity_missing";

function trackingAvailability(item: OrderPlanListItem | null): TrackingAvailability {
  if (!item || item.tracking === undefined) return "contract_missing";
  if (item.tracking === null) return "opportunity_missing";
  return "available";
}

function trackingStatusLabel(item: OrderPlanListItem | null): string {
  switch (trackingAvailability(item)) {
    case "contract_missing":
      return "계약 미구현";
    case "opportunity_missing":
      return "사업기회 미연결";
    default:
      return item?.tracking?.tracking_status === "미선택"
        ? "추적 결정 없음"
        : (item?.tracking?.tracking_status ?? "추적 결정 없음");
  }
}

/**
 * 상세 pane 본문의 추적 결정 영역.
 *
 * 결정 버튼 자체는 pane 바닥의 `ReviewDecisionBar`에 있다(ADR-0045 결정 4). 여기에는
 * 현재 상태와, 그 결정이 무엇을 바꾸지 않는지와, 사유·담당자 감사 표식만 둔다.
 */
function TrackingDecisionPanel({
  item,
  reason,
  onReasonChange,
  actorName,
  onActorNameChange,
}: {
  item: OrderPlanListItem;
  reason: string;
  onReasonChange: (value: string) => void;
  actorName: string;
  onActorNameChange: (value: string) => void;
}) {
  const availability = trackingAvailability(item);
  return (
    <section className="c2l-tracking" aria-labelledby={`c2l-tracking-${item.order_plan_pk}`}>
      <header className="c2l-tracking-head">
        <Text type="label" color="primary" as="p" id={`c2l-tracking-${item.order_plan_pk}`}>추적 결정</Text>
        <Badge
          variant={availability === "available" ? "neutral" : "warning"}
          label={trackingStatusLabel(item)}
        />
      </header>
      {/* CLAUDE.md 강제 게이트: 네 결정은 서로를 대신하지 않는다. 밀도를 낮추더라도
          이 문구를 결정 옆에서 지우지 않는다. */}
      <Text type="supporting" color="secondary" as="p">
        미선택은 추적 종료가 아닙니다. 추적 상태만 기록하며 모델 판단·적합성 등급·참여 준비 상태·최종 Go/No-Go를 바꾸지 않습니다.
      </Text>
      {availability === "contract_missing" ? (
        <Text type="supporting" color="secondary" as="p" role="status">
          추적 결정을 저장할 서버 계약이 아직 구현되지 않았습니다. 현재 추적 상태를 읽을 수 없으므로 미선택으로 표시하지 않습니다.
        </Text>
      ) : null}
      {availability === "opportunity_missing" ? (
        <Text type="supporting" color="secondary" as="p" role="status">
          이 발주계획을 소유한 사업기회를 확인하지 못했습니다. 사업기회 연결이 확인되면 이 화면에서 추적 상태를 고를 수 있습니다.
        </Text>
      ) : null}
      {item.tracking?.tracking_selected_by ? (
        <Text type="supporting" color="secondary" as="p">
          최근 선택 {item.tracking.tracking_selected_by} · {formatMoment(item.tracking.tracking_selected_at)} · 사유 <ReviewValue value={item.tracking.tracking_reason} nullLabel="null (사유 없음)" />
        </Text>
      ) : null}
      <div className="c2l-tracking-fields">
        <ReviewFilterSelector
          clearable={false}
          label="추적 결정 사유"
          onChange={(value) => onReasonChange(value ?? TRACKING_REASONS[0])}
          options={TRACKING_REASONS.map((value) => ({ label: value, value }))}
          value={reason}
        />
        <TextInput
          label="담당자 이름"
          value={actorName}
          onChange={onActorNameChange}
          description="감사 표식이며 로그인·신원 인증·권한 부여가 아닙니다."
        />
      </div>
    </section>
  );
}

function VerdictPanel({
  item,
  relevance,
  onRelevanceChange,
  priority,
  onPriorityChange,
  memo,
  onMemoChange,
  actorName,
  onActorNameChange,
  trackingReason,
  onTrackingReasonChange,
  trackingActorName,
  onTrackingActorNameChange,
  feedbackDisabledReason,
  feedbackError,
  feedbackReady,
  onSaveFeedback,
  savedMessage,
}: {
  item: OrderPlanListItem;
  relevance: OrderPlanRelevance;
  onRelevanceChange: (value: OrderPlanRelevance) => void;
  priority: OrderPlanFeedbackPriority | "";
  onPriorityChange: (value: OrderPlanFeedbackPriority | "") => void;
  memo: string;
  onMemoChange: (value: string) => void;
  actorName: string;
  onActorNameChange: (value: string) => void;
  trackingReason: string;
  onTrackingReasonChange: (value: string) => void;
  trackingActorName: string;
  onTrackingActorNameChange: (value: string) => void;
  feedbackDisabledReason?: string;
  feedbackError: string | null;
  feedbackReady: boolean;
  onSaveFeedback: () => void;
  savedMessage: string | null;
}) {
  return (
    <div className="c2l-verdict">
      <ul className="c2l-facts">
        <li><dt>발주계획 번호</dt><dd className="c2l-digest">{item.order_plan_unty_no}</dd></li>
        <li><dt>기관</dt><dd>{textOrUnknown(item.agency_name)}</dd></li>
        <li><dt>사업 분야</dt><dd>{textOrUnknown(item.business_division)}</dd></li>
        <li><dt>예산</dt><dd>{budgetLabel(item.budget_amount)}</dd></li>
        <li><dt>계획 시기</dt><dd>{plannedTiming(item.planned_order_year, item.planned_order_month)}</dd></li>
      </ul>

      {item.human_feedback ? (
        <Banner
          status="info"
          title={`최근 사람 피드백: revision ${item.human_feedback.revision}`}
          description={`${item.human_feedback.relevance} · priority ${item.human_feedback.priority ?? "null"} · ${item.human_feedback.claimed_name} · ${formatMoment(item.human_feedback.created_at)}`}
          collapsible={false}
        />
      ) : null}

      <TrackingDecisionPanel
        actorName={trackingActorName}
        item={item}
        onActorNameChange={onTrackingActorNameChange}
        onReasonChange={onTrackingReasonChange}
        reason={trackingReason}
      />

      {/* 접힌 보조 입력 영역(PLAN 단계 B·C). pane 바닥의 결정은 추적 결정이고 이 입력은
          선택 사항이므로 기본이 접힘이다(ADR-0045 결정 5). 접어도 현재 사람 판단 값과
          "무엇을 바꾸지 않는가"는 머리에 남고 입력만 숨는다. 저장은 추적 결정과 공유하지
          않고 이 영역이 소유한다. */}
      <ReviewSecondaryInput
        description="기존 사람 판단을 유지합니다. 추적 결정과는 별도 revision이며 적합성 등급·참여 준비 상태·심층 추적 승인·최종 Go/No-Go를 채우거나 대신하지 않습니다."
        summary={(
          <Badge
            variant="neutral"
            label={item.human_feedback
              ? `${item.human_feedback.relevance} · 우선순위 ${item.human_feedback.priority ?? "미지정"}`
              : "사람 판단 미입력"}
          />
        )}
        title="사람 판단 수정 (선택)"
      >
        <div className="c2l-feedback-field">
          <Text type="label" color="secondary" as="p" id={`c2l-relevance-label-${item.order_plan_pk}`}>relevance</Text>
          <SegmentedControl value={relevance} onChange={(value) => onRelevanceChange(value as OrderPlanRelevance)} label="사람 relevance 판단">
            <SegmentedControlItem value="relevant" label="relevant" />
            <SegmentedControlItem value="uncertain" label="uncertain" />
            <SegmentedControlItem value="not_relevant" label="not_relevant" />
          </SegmentedControl>
        </div>

        <div className="c2l-feedback-field">
          <Text type="label" color="secondary" as="p">priority</Text>
          <SegmentedControl value={priority || "null"} onChange={(value) => onPriorityChange(value === "null" ? "" : (value as OrderPlanFeedbackPriority))} label="사람 priority 판단">
            <SegmentedControlItem value="high" label="high" />
            <SegmentedControlItem value="medium" label="medium" />
            <SegmentedControlItem value="low" label="low" />
            <SegmentedControlItem value="null" label="null · 미지정" />
          </SegmentedControl>
        </div>

        <TextArea
          label="memo"
          value={memo}
          onChange={onMemoChange}
          rows={3}
          placeholder="사람 검토 근거 또는 다음 확인 사항"
        />

        <TextInput
          label="담당자 claimed name"
          value={actorName}
          onChange={onActorNameChange}
          description="감사 귀속용 이름이며 로그인·신원 인증·권한 부여가 아닙니다."
        />

        <div className="c2l-feedback-actions">
          {feedbackError ? <Text type="body" color="secondary" role="alert">{feedbackError}</Text> : null}
          {savedMessage ? <Text type="body" color="secondary" role="status">{savedMessage}</Text> : null}
          <ReviewDecisionAction
            disabledReason={feedbackDisabledReason}
            isDisabled={!feedbackReady}
            label="새 revision 저장"
            variant="secondary"
            onClick={onSaveFeedback}
          />
        </div>
      </ReviewSecondaryInput>
    </div>
  );
}

function OrderPlanRow({
  item,
  isSelected,
  onSelect,
  returnSearch,
}: {
  item: OrderPlanListItem;
  isSelected: boolean;
  onSelect: () => void;
  returnSearch: string;
}) {
  return (
    <DenseListRow
      aria-label={textOrUnknown(item.title)}
      className={`c2l-row-wrap c2l-row${isSelected ? " is-selected" : ""}`.trim()}
      description={
        <>
          <span className="c2l-row-badges">
            <Badge variant={stage1BadgeVariant(item.stage1_status)} label={stage1RowLabel(item.stage1_status)} />
            <Badge variant={qwenBadgeVariant(item)} label={qwenRowLabel(item)} />
            <Badge variant="neutral" label={item.human_feedback ? `피드백 rev ${item.human_feedback.revision}` : "피드백 없음"} />
          </span>
          <Text type="supporting" color="secondary" as="span">
            {textOrUnknown(item.agency_name)} · {budgetLabel(item.budget_amount)} · {plannedTiming(item.planned_order_year, item.planned_order_month)}
          </Text>
        </>
      }
      endContent={
        <Link className="c2l-row-detail-link" to={`/order-plans/${item.order_plan_pk}${returnSearch ? `?${returnSearch}` : ""}`}>
          전체 상세 열기 →
        </Link>
      }
      label={
        <span className="c2l-row-line">
          <Text type="body" color="primary" maxLines={1}>{textOrUnknown(item.title)}</Text>
        </span>
      }
      onSelect={onSelect}
      selected={isSelected}
    />
  );
}

export function OrderPlansPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const queryClient = useQueryClient();

  const [searchText, setSearchText] = useState(searchParams.get("q") ?? "");
  const [detailTab, setDetailTab] = useState<DetailTab>("verdict");
  const [listWidth, setListWidth] = useState<number>(() => loadListWidth());
  const [savedViews, setSavedViews] = useState<SavedView[]>(() => loadSavedViews());
  const [newViewName, setNewViewName] = useState("");
  const [isNamingView, setIsNamingView] = useState(false);
  const [descriptionOpen, setDescriptionOpen] = useState<boolean | null>(null);

  const [trackingReason, setTrackingReason] = useState<string>(TRACKING_REASONS[0]);
  const [trackingActor, setTrackingActor] = useState("");
  // 결정 뒤의 안내는 **이동한 뒤의 건**에 붙는다. 선택이 바뀌면 사라지되, 그 이동을 만든
  // 결정의 안내는 남아야 하므로 어느 건에서 보일 문구인지를 함께 들고 다닌다.
  const [trackingMessage, setTrackingMessage] = useState<{ pk: number; text: string } | null>(null);

  const [relevance, setRelevance] = useState<OrderPlanRelevance>("uncertain");
  const [priority, setPriority] = useState<OrderPlanFeedbackPriority | "">("");
  const [memo, setMemo] = useState("");
  const [actorName, setActorName] = useState("");
  const [savedMessage, setSavedMessage] = useState<string | null>(null);
  const dragStateRef = useRef<{ startX: number; startWidth: number } | null>(null);

  useEffect(() => setSearchText(searchParams.get("q") ?? ""), [searchParams]);

  const isDefaultView = !AXIS_KEYS.some((key) => searchParams.has(key));
  const qwenSet = isDefaultView ? new Set<RelevanceToken>(["relevant", "uncertain"]) : parseTokenSet(searchParams.get("qwen"), RELEVANCE_TOKENS);
  const stage1Set = isDefaultView ? new Set<Stage1Token>() : parseTokenSet(searchParams.get("stage1"), STAGE1_TOKENS);
  const feedbackSet = isDefaultView ? new Set<FeedbackToken>() : parseTokenSet(searchParams.get("feedback"), FEEDBACK_TOKENS);
  const issueOn = !isDefaultView && searchParams.get("issue") === "yes";
  const qText = searchParams.get("q") ?? "";
  const offsetRaw = Number(searchParams.get("offset") ?? "0");
  const offset = Number.isFinite(offsetRaw) && offsetRaw >= 0 ? Math.floor(offsetRaw / PAGE_SIZE) * PAGE_SIZE : 0;
  const selectedParam = searchParams.get("selected");
  const selectedPk = selectedParam ? Number(selectedParam) : null;

  const activePreset = (() => {
    if (qText) return null;
    for (const preset of PRESETS) {
      if (
        setEqualsArray(qwenSet, preset.axes.qwen)
        && setEqualsArray(stage1Set, preset.axes.stage1)
        && setEqualsArray(feedbackSet, preset.axes.feedback)
        && issueOn === preset.axes.issue
      ) return preset.key;
    }
    return null;
  })();

  function applyAxes(next: { qwen?: Set<RelevanceToken>; stage1?: Set<Stage1Token>; feedback?: Set<FeedbackToken>; issue?: boolean; q?: string }) {
    const params = new URLSearchParams(searchParams);
    if (next.qwen) params.set("qwen", serializeTokens(next.qwen));
    if (next.stage1) params.set("stage1", serializeTokens(next.stage1));
    if (next.feedback) params.set("feedback", serializeTokens(next.feedback));
    if (next.issue !== undefined) params.set("issue", next.issue ? "yes" : "");
    if (next.q !== undefined) params.set("q", next.q);
    params.delete("offset");
    setSearchParams(params, { replace: true });
  }

  function applyPreset(presetKey: string) {
    const preset = PRESETS.find((item) => item.key === presetKey);
    if (!preset) return;
    applyAxes({
      qwen: new Set(preset.axes.qwen),
      stage1: new Set(preset.axes.stage1),
      feedback: new Set(preset.axes.feedback),
      issue: preset.axes.issue,
      q: "",
    });
    setSearchText("");
  }

  function applySavedViewSearch(search: string) {
    const savedParams = new URLSearchParams(search);
    const params = new URLSearchParams(searchParams);
    for (const key of AXIS_KEYS) {
      if (savedParams.has(key)) params.set(key, savedParams.get(key) ?? "");
      else params.delete(key);
    }
    params.delete("offset");
    setSearchParams(params, { replace: true });
    setSearchText(savedParams.get("q") ?? "");
  }

  function resetFilters() {
    const params = new URLSearchParams(searchParams);
    for (const key of AXIS_KEYS) params.delete(key);
    params.delete("offset");
    setSearchParams(params, { replace: true });
    setSearchText("");
  }

  function saveCurrentAsView() {
    const name = newViewName.trim();
    if (!name) return;
    const params = new URLSearchParams();
    params.set("qwen", serializeTokens(qwenSet));
    params.set("stage1", serializeTokens(stage1Set));
    params.set("feedback", serializeTokens(feedbackSet));
    params.set("issue", issueOn ? "yes" : "");
    params.set("q", qText);
    const view: SavedView = { id: requestId(), name, search: params.toString(), createdAt: new Date().toISOString() };
    const next = [...savedViews, view];
    setSavedViews(next);
    persistSavedViews(next);
    setNewViewName("");
    setIsNamingView(false);
  }

  function deleteSavedView(id: string) {
    const next = savedViews.filter((view) => view.id !== id);
    setSavedViews(next);
    persistSavedViews(next);
  }

  function selectRow(pk: number) {
    const params = new URLSearchParams(searchParams);
    params.set("selected", String(pk));
    setSearchParams(params, { replace: true });
  }

  const executionsQuery = useQuery({
    queryKey: ["order-plan-c2", "executions"],
    queryFn: ({ signal }) => fetchAllExecutions(signal),
    staleTime: 15_000,
  });
  const executions = executionsQuery.data?.items ?? [];
  const latestExecution = latestCompletedExecution(executions);

  const listQuery = useQuery({
    queryKey: ["order-plan-c2", "list", latestExecution?.source_run_id],
    queryFn: ({ signal }) => fetchAllOrderPlans(latestExecution?.source_run_id as string, signal),
    enabled: Boolean(latestExecution?.source_run_id),
    staleTime: 15_000,
  });

  const executionDetailQuery = useQuery({
    queryKey: ["order-plan-c2", "execution-detail", latestExecution?.execution_id],
    queryFn: ({ signal }) => api.getOrderPlanScreeningExecution(latestExecution?.execution_id as string, { signal }),
    enabled: Boolean(latestExecution?.execution_id),
    staleTime: 15_000,
  });

  function matchesFilters(item: OrderPlanListItem): boolean {
    if (qwenSet.size && !qwenSet.has(relevanceToken(item.qwen_relevance))) return false;
    if (stage1Set.size && !stage1Set.has(stage1Token(item.stage1_status))) return false;
    if (feedbackSet.size) {
      const token: FeedbackToken = item.human_feedback ? "has" : "none";
      if (!feedbackSet.has(token)) return false;
    }
    if (issueOn && !isExecutionIssue(item)) return false;
    if (qText) {
      const haystack = `${item.title ?? ""} ${item.order_plan_unty_no}`.toLocaleLowerCase("ko-KR");
      if (!haystack.includes(qText.toLocaleLowerCase("ko-KR"))) return false;
    }
    return true;
  }

  const allItems = listQuery.data?.items ?? [];
  const filteredItems = allItems.filter(matchesFilters);
  const total = filteredItems.length;
  const visibleItems = filteredItems.slice(offset, offset + PAGE_SIZE);
  const hasPrevious = offset > 0;
  const hasNext = offset + visibleItems.length < total;

  const selectedItem = (selectedPk !== null ? filteredItems.find((item) => item.order_plan_pk === selectedPk) : undefined) ?? visibleItems[0] ?? null;

  useEffect(() => {
    if (!visibleItems.length) return;
    const stillValid = selectedPk !== null && filteredItems.some((item) => item.order_plan_pk === selectedPk);
    if (stillValid) return;
    const params = new URLSearchParams(searchParams);
    params.set("selected", String(visibleItems[0].order_plan_pk));
    setSearchParams(params, { replace: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [visibleItems.map((item) => item.order_plan_pk).join(","), selectedPk]);

  useEffect(() => {
    setRelevance("uncertain");
    setPriority("");
    setMemo("");
  }, [selectedItem?.order_plan_pk]);

  /** 다음 건으로 이동하고 그 건의 PK를 돌려준다. 마지막 건이면 현재 PK를 그대로 돌려준다. */
  function advanceToNext(): number | null {
    if (!selectedItem) return null;
    const idx = filteredItems.findIndex((item) => item.order_plan_pk === selectedItem.order_plan_pk);
    if (idx === -1 || idx + 1 >= filteredItems.length) return selectedItem.order_plan_pk;
    const nextItem = filteredItems[idx + 1];
    const params = new URLSearchParams(searchParams);
    params.set("selected", String(nextItem.order_plan_pk));
    if (idx + 1 >= offset + PAGE_SIZE) params.set("offset", String(offset + PAGE_SIZE));
    setSearchParams(params, { replace: true });
    return nextItem.order_plan_pk;
  }

  const expectedRevision = selectedItem?.human_feedback?.revision ?? 0;

  const mutation = useMutation({
    mutationFn: () => api.createOrderPlanScreeningFeedback(
      (selectedItem as OrderPlanListItem).order_plan_pk,
      {
        schema_version: "feedback-create-request.v1",
        producer: "human-review-client",
        consumer: "review-api",
        request_id: requestId(),
        execution_id: (latestExecution as OrderPlanScreeningExecutionSummary).execution_id,
        relevance,
        priority: priority || null,
        memo: memo.trim() || null,
        expected_revision: expectedRevision,
      },
      actorName,
    ),
    onSuccess: async () => {
      setSavedMessage("사람 피드백 revision을 저장했습니다. 추적 상태는 바뀌지 않았습니다.");
      await queryClient.invalidateQueries({ queryKey: ["order-plan-c2", "list"] });
    },
  });

  const ready = Boolean(selectedItem) && Boolean(latestExecution) && actorName.trim().length > 0;
  const decisionDisabledReason = !actorName.trim() ? "담당자 claimed name을 입력하면 저장할 수 있습니다." : undefined;

  // 사람 판단 수정은 저장만 하고 다음 건으로 이동하지 않는다. 이동은 추적 결정이 소유한다.
  function handleSave() {
    if (!ready) return;
    setSavedMessage(null);
    mutation.mutate();
  }

  // --- 추적 결정 (결정 1) ---
  //
  // 사람 판단 수정(`mutation`)과 **다른 mutation·다른 경로**다. ADR-0045 결정 5가 둘을
  // 분리하도록 요구하므로 한 요청으로 합치지 않는다.
  //
  // 서버 계약은 아직 없다(order-plan-tracking-contract-request.md). 그래서 낙관적 갱신을
  // 하지 않는다 — 성공 응답을 받은 뒤에만 목록을 다시 읽고 다음 건으로 이동한다. 실패하면
  // 이 건의 추적 상태를 바꾸지 않고 이동하지도 않는다(요청안 §7 규칙 2).
  const trackingAvailabilityState = trackingAvailability(selectedItem);

  const trackingMutation = useMutation({
    mutationFn: (status: OrderPlanTrackingDecisionStatus) => api.createOrderPlanTrackingDecision(
      (selectedItem as OrderPlanListItem).order_plan_pk,
      {
        schema_version: "order-plan-tracking-decision-create.v1",
        producer: "order-plan-review-client",
        consumer: "order-plan-review-api",
        request_id: requestId(),
        tracking_status: status,
        reason: trackingReason,
        expected_tracking_status: selectedItem?.tracking?.tracking_status ?? null,
      },
      trackingActor,
    ),
    onSuccess: async (saved) => {
      await queryClient.invalidateQueries({ queryKey: ["order-plan-c2", "list"] });
      const nextPk = advanceToNext();
      if (nextPk !== null) {
        setTrackingMessage({ pk: nextPk, text: `추적 상태를 ${saved.tracking_status}(으)로 기록했습니다. 다음 발주계획으로 이동합니다.` });
      }
    },
  });

  const trackingDisabledReason = trackingAvailabilityState === "contract_missing"
    ? "추적 결정을 저장할 서버 계약이 아직 구현되지 않았습니다."
    : trackingAvailabilityState === "opportunity_missing"
      ? "이 발주계획을 소유한 사업기회를 확인하지 못해 추적 결정을 기록할 수 없습니다."
      : !trackingActor.trim()
        ? "담당자 이름을 입력하면 추적 결정을 기록할 수 있습니다."
        : trackingMutation.isPending
          ? "추적 결정 저장 요청을 처리하고 있습니다."
          : undefined;
  const trackingReady = Boolean(selectedItem) && trackingDisabledReason === undefined;

  function decideTracking(status: OrderPlanTrackingDecisionStatus) {
    if (!trackingReady) return;
    setTrackingMessage(null);
    trackingMutation.mutate(status);
  }

  // 실패 안내도 그 건을 떠나면 사라져야 한다. 다른 건의 결정 바에 남은 오류는 거짓이다.
  useEffect(() => {
    trackingMutation.reset();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedItem?.order_plan_pk]);

  /** 저장하지 않는다. 상태를 미선택에 그대로 두고 다음 건으로만 이동한다(요청안 §4). */
  function skipCurrent() {
    trackingMutation.reset();
    const nextPk = advanceToNext();
    if (nextPk !== null) {
      setTrackingMessage({ pk: nextPk, text: "추적 상태를 바꾸지 않고 다음 발주계획으로 이동했습니다. 미선택은 추적 종료가 아닙니다." });
    }
  }

  function updateListWidth(next: number) {
    const clamped = Math.min(MAX_LIST_WIDTH, Math.max(MIN_LIST_WIDTH, next));
    setListWidth(clamped);
    saveListWidth(clamped);
  }

  useEffect(() => {
    function onMove(event: MouseEvent) {
      if (!dragStateRef.current) return;
      const delta = event.clientX - dragStateRef.current.startX;
      updateListWidth(dragStateRef.current.startWidth + delta);
    }
    function onUp() {
      dragStateRef.current = null;
    }
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const listError = listQuery.error instanceof ApiError ? listQuery.error.message : "발주계획 목록을 확인할 수 없습니다.";
  const executionError = executionsQuery.error instanceof ApiError ? executionsQuery.error.message : "C-2 실행 목록을 확인할 수 없습니다.";
  const returnSearch = searchParams.toString();
  const hasProblem = executionsQuery.isPending || executionHasProblem(latestExecution, executions);
  const descriptionIsOpen = descriptionOpen ?? hasProblem;
  // 목록 머리글이 "무엇을 보고 있는가"를 문장으로 밝힌다. 축 안은 OR, 축끼리는 AND다.
  const filterMeaning = (() => {
    if (isDefaultView) return "기본 보기 · BM25 선정 AND 모델 판단 관련·불확실";
    const parts: string[] = [];
    if (stage1Set.size) parts.push(`BM25 ${Array.from(stage1Set).join("·")}`);
    if (qwenSet.size) parts.push(`모델 판단 ${Array.from(qwenSet).join("·")}`);
    if (feedbackSet.size) parts.push(`사람 판단 ${Array.from(feedbackSet).map((token) => (token === "has" ? "있음" : "없음")).join("·")}`);
    if (issueOn) parts.push("실패·거부만");
    if (qText.trim()) parts.push(`검색 "${qText.trim()}"`);
    return parts.length ? parts.join(" AND ") : "전체";
  })();

  const activeFilterCount = isDefaultView
    ? 0
    : qwenSet.size + stage1Set.size + feedbackSet.size + (issueOn ? 1 : 0) + (qText.trim() ? 1 : 0);

  return (
    <section className="c2l-page" data-astryx-theme="bidops" aria-labelledby="order-plans-title">
      <Heading level={2} id="order-plans-title">발주계획 C-2 검토</Heading>

      {/* 시안 `Main`의 상단 한 줄. 이 화면의 데이터 축과 정책, 회차 선택기가 없다는 사실을
          한 자리에서 밝힌다(ADR-0045 결정 7, PRD §3.2). */}
      <div className="c2l-scope-line">
        <Text type="supporting" color="secondary" as="p">
          누적 데이터 · C-2 relevance 정책 · 회차 선택기 없음
        </Text>
        {latestExecution?.source_run_id ? (
          <Link className="c2l-scope-link" to={`/run-status?run=${encodeURIComponent(latestExecution.source_run_id)}`}>
            실행 상세 →
          </Link>
        ) : null}
      </div>

      <Collapsible
        isOpen={descriptionIsOpen}
        onOpenChange={setDescriptionOpen}
        trigger={<ExecutionSummaryLine latest={latestExecution} executions={executions} />}
      >
        <div className="c2l-description">
          <Text type="body" color="secondary" as="p">
            BM25 후보 신호와 Qwen relevance 신호를 분리해 최신 성공/부분 성공 실행을 검토합니다. 이 relevance는 tracking state, fitness grade, readiness, 최종 Go/No-Go가 아닙니다.
          </Text>
          <Text type="supporting" color="secondary" as="p">
            <code>filtered_out</code>는 BM25 탈락, <code>not_relevant</code>는 Qwen relevance, <code>unknown</code>은 정보 부족, <code>null</code>은 값 없음/미적용이며 서로 바꾸지 않습니다.
          </Text>
        </div>
      </Collapsible>

      {executionsQuery.isPending ? <Text type="body" color="secondary" as="p" role="status">C-2 실행 목록을 불러오는 중…</Text> : null}
      {executionsQuery.isError ? (
        <Banner status="error" title="C-2 실행 목록을 불러오지 못했습니다." description={executionError} collapsible={false}
          endContent={<Button label="다시 시도" size="sm" onClick={() => void executionsQuery.refetch()} />} />
      ) : null}

      {!executionsQuery.isPending && !executionsQuery.isError && !latestExecution ? <ExecutionMissingBlock executions={executions} /> : null}

      {latestExecution ? (
        <div className="c2l-workspace-shell">
          <ReviewFilterBar
            activeFilterCount={activeFilterCount}
            aria-label="C-2 결과 필터"
            className="c2l-filters"
            onReset={resetFilters}
            resetLabel="필터 초기화"
          >
            {/* 시안 `Main`의 `저장된 뷰` 는 단일 선택이므로 버튼 나열이 아니라 segmented
                control 이다(PLAN 단계 C 작업 2). 조합 필터의 AND/OR 의미와 URL 동기화는
                아래 축들이 그대로 소유한다 — 이 컨트롤은 이름 붙은 지름길일 뿐이다. */}
            <div className="c2l-presets">
              <Text type="label" color="secondary" as="p" id="c2l-saved-view-label">저장된 뷰</Text>
              <ReviewFilterSegmentedControl
                label="저장된 뷰"
                onChange={applyPreset}
                options={PRESETS.map((preset) => ({ label: preset.label, value: preset.key }))}
                value={activePreset ?? ""}
              />
            </div>

            <div className="c2l-filter-axis">
              <Text type="label" color="secondary" as="p">Qwen relevance</Text>
              <ToggleButtonGroup
                type="multiple"
                label="Qwen relevance 필터"
                value={Array.from(qwenSet)}
                onChange={(value) => applyAxes({ qwen: new Set(value as RelevanceToken[]) })}
              >
                <ToggleButton value="relevant" label="relevant" />
                <ToggleButton value="uncertain" label="uncertain" />
                <ToggleButton value="not_relevant" label="not_relevant" />
                <ToggleButton value="null" label="null · 값 없음" />
              </ToggleButtonGroup>
            </div>

            <div className="c2l-filter-axis">
              <Text type="label" color="secondary" as="p">BM25 stage1</Text>
              <ToggleButtonGroup
                type="multiple"
                label="BM25 stage1 필터"
                value={Array.from(stage1Set)}
                onChange={(value) => applyAxes({ stage1: new Set(value as Stage1Token[]) })}
              >
                <ToggleButton value="selected" label="selected" />
                <ToggleButton value="filtered_out" label="filtered_out" />
                <ToggleButton value="failed" label="failed" />
                <ToggleButton value="rejected" label="rejected" />
                <ToggleButton value="null" label="null · 값 없음" />
              </ToggleButtonGroup>
            </div>

            <div className="c2l-filter-axis">
              <Text type="label" color="secondary" as="p">사람 피드백</Text>
              <ToggleButtonGroup
                type="multiple"
                label="사람 피드백 필터"
                value={Array.from(feedbackSet)}
                onChange={(value) => applyAxes({ feedback: new Set(value as FeedbackToken[]) })}
              >
                <ToggleButton value="has" label="있음" />
                <ToggleButton value="none" label="없음" />
              </ToggleButtonGroup>
            </div>

            <div className="c2l-filter-axis">
              <Text type="label" color="secondary" as="p">실행 결과</Text>
              <ToggleButton
                value="issue"
                label="실패·거부만"
                isPressed={issueOn}
                onPressedChange={(pressed) => applyAxes({ issue: pressed })}
              />
            </div>

            <div className="c2l-filter-axis">
              <ReviewFilterTextInput
                label="제목·계획번호 검색"
                value={searchText}
                onChange={setSearchText}
                onEnter={() => applyAxes({ q: searchText })}
                placeholder="검색어"
              />
              <Button label="검색" size="sm" onClick={() => applyAxes({ q: searchText })} />
            </div>

            <div className="c2l-filter-axis c2l-saved-views">
              <ReviewFilterSelector
                clearable={false}
                label="저장된 뷰"
                options={savedViews.map((view) => ({ value: view.id, label: view.name }))}
                value=""
                onChange={(id) => {
                  const view = savedViews.find((item) => item.id === id);
                  if (view) applySavedViewSearch(view.search);
                }}
                placeholder={savedViews.length ? "저장된 뷰 선택" : "저장된 뷰 없음"}
                isDisabled={savedViews.length === 0}
              />
              {isNamingView ? (
                <>
                  <ReviewFilterTextInput label="뷰 이름" value={newViewName} onChange={setNewViewName} placeholder="뷰 이름" onEnter={saveCurrentAsView} />
                  <Button label="뷰 저장" size="sm" onClick={saveCurrentAsView} isDisabled={!newViewName.trim()} />
                  <Button label="취소" size="sm" variant="ghost" onClick={() => { setIsNamingView(false); setNewViewName(""); }} />
                </>
              ) : (
                <Button label="현재 필터를 뷰로 저장" size="sm" variant="ghost" onClick={() => setIsNamingView(true)} />
              )}
              {savedViews.length ? (
                <ul className="c2l-saved-view-list">
                  {savedViews.map((view) => (
                    <li key={view.id}>
                      <Text type="supporting" color="secondary" as="span">{view.name}</Text>
                      <Button label={`${view.name} 삭제`} isIconOnly icon={<span aria-hidden="true">×</span>} size="sm" variant="ghost" onClick={() => deleteSavedView(view.id)} />
                    </li>
                  ))}
                </ul>
                ) : null}
            </div>
          </ReviewFilterBar>

          {listQuery.isPending ? <Text type="body" color="secondary" as="p" role="status">발주계획을 불러오는 중…</Text> : null}
          {listQuery.isError ? (
            <Banner status="error" title="발주계획 목록을 불러오지 못했습니다." description={listError} collapsible={false}
              endContent={<Button label="다시 시도" size="sm" onClick={() => void listQuery.refetch()} />} />
          ) : null}

          {!listQuery.isPending && !listQuery.isError ? (
            <SplitWorkspace
              aria-label="발주계획 목록과 상세"
              className="c2l-workspace"
              style={{ "--c2l-list-width": `${listWidth}px` } as React.CSSProperties}
            >
              <aside className="c2l-list-pane">
                <header className="c2l-list-head">
                  <Text type="label" color="primary" as="p">발주계획 목록</Text>
                  <Text type="supporting" color="secondary" as="p">{filterMeaning} · 현재 필터 결과 {total.toLocaleString("ko-KR")}건 · {visibleItems.length ? offset + 1 : 0}–{Math.min(offset + visibleItems.length, total)} / {total.toLocaleString("ko-KR")}</Text>
                </header>
                {visibleItems.length === 0 ? (
                  <div className="c2l-list-empty">
                    <Text type="body" color="secondary" as="p">현재 필터에 해당하는 결과가 없습니다. 표시되지 않은 값이나 실행 실패를 다른 relevance 상태로 바꾸지 않습니다.</Text>
                  </div>
                ) : (
                  <DenseList aria-label="발주계획 검토 목록" className="c2l-list-scroll">
                    {visibleItems.map((item) => (
                      <OrderPlanRow
                        key={item.order_plan_pk}
                        item={item}
                        isSelected={selectedItem?.order_plan_pk === item.order_plan_pk}
                        onSelect={() => selectRow(item.order_plan_pk)}
                        returnSearch={returnSearch}
                      />
                    ))}
                  </DenseList>
                )}
                {/* 기본 보기가 숨기는 것을 목록 바닥에 밝힌다. 숨김을 부재로 표시하지
                    않는다(PRD §3.2). */}
                {isDefaultView ? (
                  <p className="c2l-list-foot">
                    <Text type="supporting" color="secondary" as="span">
                      필터 외 BM25 선정 제외·비관련·실패 건은 기본 보기에서 숨김. 없는 것이 아니라 보이지 않는 것입니다.
                    </Text>
                  </p>
                ) : null}
                {hasPrevious || hasNext ? (
                  <nav className="c2l-pager" aria-label="발주계획 목록 페이지">
                    <Button label="이전" size="sm" variant="secondary" isDisabled={!hasPrevious} onClick={() => {
                      const params = new URLSearchParams(searchParams);
                      params.set("offset", String(Math.max(0, offset - PAGE_SIZE)));
                      setSearchParams(params, { replace: true });
                    }} />
                    <Text type="supporting" color="secondary">{(offset + 1).toLocaleString("ko-KR")}–{Math.min(offset + visibleItems.length, total).toLocaleString("ko-KR")} / {total.toLocaleString("ko-KR")}</Text>
                    <Button label="다음" size="sm" variant="secondary" isDisabled={!hasNext} onClick={() => {
                      const params = new URLSearchParams(searchParams);
                      params.set("offset", String(offset + PAGE_SIZE));
                      setSearchParams(params, { replace: true });
                    }} />
                  </nav>
                ) : null}
              </aside>

              <div
                className="c2l-resizer"
                role="separator"
                aria-orientation="vertical"
                aria-label="목록 폭 조절"
                aria-valuemin={MIN_LIST_WIDTH}
                aria-valuemax={MAX_LIST_WIDTH}
                aria-valuenow={listWidth}
                tabIndex={0}
                onMouseDown={(event) => { dragStateRef.current = { startX: event.clientX, startWidth: listWidth }; }}
                onKeyDown={(event) => {
                  if (event.key === "ArrowLeft") { updateListWidth(listWidth - LIST_WIDTH_STEP); event.preventDefault(); }
                  else if (event.key === "ArrowRight") { updateListWidth(listWidth + LIST_WIDTH_STEP); event.preventDefault(); }
                  else if (event.key === "Home") { updateListWidth(MIN_LIST_WIDTH); event.preventDefault(); }
                  else if (event.key === "End") { updateListWidth(MAX_LIST_WIDTH); event.preventDefault(); }
                }}
              />

              <section className="c2l-detail-pane">
                {selectedItem ? (
                  <>
                    <StickyDecisionHeader className="c2l-detail-head" label="발주계획 상세 헤더">
                      <Text type="supporting" color="secondary" as="p">발주계획 {selectedItem.order_plan_unty_no} · 계획 ID {selectedItem.order_plan_pk}</Text>
                      <Heading level={4}>{textOrUnknown(selectedItem.title)}</Heading>
                      <TabList value={detailTab} onChange={(value) => setDetailTab(value as DetailTab)} role="tablist" hasDivider>
                        <Tab value="verdict" label="판정" panelId="c2l-panel-verdict" />
                        <Tab value="signals" label="신호 세부" panelId="c2l-panel-signals" />
                        <Tab value="telemetry" label="실행 기록" panelId="c2l-panel-telemetry" />
                      </TabList>
                    </StickyDecisionHeader>
                    <div className="c2l-detail-scroll">
                      <div id="c2l-panel-verdict" role="tabpanel" aria-label="판정" hidden={detailTab !== "verdict"}>
                        <VerdictPanel
                          item={selectedItem}
                          relevance={relevance}
                          onRelevanceChange={setRelevance}
                          priority={priority}
                          onPriorityChange={setPriority}
                          memo={memo}
                          onMemoChange={setMemo}
                          actorName={actorName}
                          onActorNameChange={setActorName}
                          trackingReason={trackingReason}
                          onTrackingReasonChange={setTrackingReason}
                          trackingActorName={trackingActor}
                          onTrackingActorNameChange={setTrackingActor}
                          feedbackDisabledReason={decisionDisabledReason}
                          feedbackError={mutation.isError ? (mutation.error instanceof ApiError ? mutation.error.message : "사람 피드백을 저장하지 못했습니다.") : null}
                          feedbackReady={ready && !mutation.isPending}
                          onSaveFeedback={handleSave}
                          savedMessage={savedMessage}
                        />
                      </div>
                      <div id="c2l-panel-signals" role="tabpanel" aria-label="신호 세부" hidden={detailTab !== "signals"}>
                        <SignalPanel item={selectedItem} />
                      </div>
                      <div id="c2l-panel-telemetry" role="tabpanel" aria-label="실행 기록" hidden={detailTab !== "telemetry"}>
                        <TelemetryPanel
                          execution={latestExecution}
                          detail={executionDetailQuery.data}
                          detailPending={executionDetailQuery.isPending}
                          detailError={executionDetailQuery.error}
                        />
                      </div>
                    </div>
                    {/* 분할 화면의 결정 액션은 상세 pane 바닥에 둔다. 단독
                        상세 화면(OrderPlanDetailPage)은 sticky 헤더에 두며, 두
                        배치를 한 화면에서 섞지 않는다(PLAN 단계 B).
                        여기의 결정은 **추적 결정 하나**다(ADR-0045 결정 4). 사람 판단
                        수정은 접힌 보조 입력 영역이 자기 저장을 소유한다. */}
                    <ReviewDecisionBar
                      className="c2l-detail-actions"
                      hint={(
                        <>
                          선택 즉시 이력을 기록하고 다음 발주계획으로 이동합니다 · 별도 저장 없음
                          <br />
                          {filteredItems.findIndex((item) => item.order_plan_pk === selectedItem.order_plan_pk) + 1} / {total}
                        </>
                      )}
                      label="발주계획 추적 결정"
                      status={(
                        <>
                          {trackingMutation.isError ? (
                            <Text type="body" color="secondary" role="alert">
                              {trackingMutation.error instanceof ApiError ? trackingMutation.error.message : "추적 결정을 저장하지 못했습니다."} 이 발주계획의 추적 상태는 바뀌지 않았습니다.
                            </Text>
                          ) : null}
                          {trackingMessage?.pk === selectedItem.order_plan_pk ? <Text type="body" color="secondary" role="status">{trackingMessage.text}</Text> : null}
                        </>
                      )}
                      actions={(
                        <>
                          {/* 세 결정이 같은 사유로 함께 막힌다. 첫 액션이 그 문구를
                              한 번만 그리고 나머지는 같은 id를 가리켜, 화면에 같은
                              문장이 세 번 쌓이지 않으면서 각 버튼이 사유를 읽는다. */}
                          <ReviewDecisionAction
                            disabledReason={trackingDisabledReason}
                            disabledReasonId="c2l-tracking-decision-reason"
                            isDisabled={!trackingReady}
                            label="추적 시작"
                            variant="primary"
                            onClick={() => decideTracking("계속 추적")}
                          />
                          <ReviewDecisionAction
                            disabledReasonId="c2l-tracking-decision-reason"
                            isDisabled={!trackingReady}
                            label="보류"
                            variant="secondary"
                            onClick={() => decideTracking("보류")}
                          />
                          <ReviewDecisionAction
                            disabledReasonId="c2l-tracking-decision-reason"
                            isDisabled={!trackingReady}
                            label="추적 종료"
                            variant="secondary"
                            onClick={() => decideTracking("종료")}
                          />
                          {/* 아무것도 저장하지 않으므로 계약이 없어도 비활성이 아니다. */}
                          <ReviewDecisionAction
                            label="이번 건 넘기기"
                            variant="ghost"
                            onClick={skipCurrent}
                          />
                        </>
                      )}
                    />
                  </>
                ) : (
                  <div className="c2l-detail-empty">
                    <Text type="body" color="secondary" as="p">표시할 발주계획이 없습니다.</Text>
                  </div>
                )}
              </section>
            </SplitWorkspace>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
