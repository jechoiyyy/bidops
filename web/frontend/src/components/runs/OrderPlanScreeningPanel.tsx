import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { Button } from "@astryxdesign/core/Button";
import { Text } from "@astryxdesign/core/Text";
import { Caption, DataTable, Facts, Note, Section, StatusToken } from "./RunStatusPrimitives";
import { api } from "../../lib/api";
import { formatDateTime, formatNumber } from "../../lib/format";
import type {
  OrderPlanListItem,
  OrderPlanScreeningAttemptStatus,
  OrderPlanScreeningExecutionPurpose,
  OrderPlanScreeningExecutionSummary,
  OrderPlanArtifactValidationStatus,
} from "../../lib/types";

/**
 * 발주계획 선별(C-2) 실행 기록의 **운영 수신처**(spec §4, ADR-0065 결정 6).
 *
 * 지금까지 C-2 실행의 배치별 토큰·소요 시간·산출물 sha256과 계획별 신호는 실무
 * 화면인 발주계획 목록의 다이얼로그에만 있었다. 이 탭이 그 값을 운영 화면에서
 * 읽을 자리를 먼저 만든다 — 어떤 값도 "옮기는 중"이라는 이유로 저장소의 어느
 * 화면에서도 읽을 수 없는 상태를 거치지 않는다.
 *
 * 운영 화면이므로 모델 이름·계약 토큰(`selected`·`relevant`·`success`…)은 원문
 * 그대로 두고 제목만 사람 말로 붙인다. 운영자가 로그와 대조하는 값이기 때문이다.
 * 식별자와 해시는 줄이지 않고 전문을 보인다(ADR-0065 결정 2).
 */

/** 계획별 신호 한 페이지. 회차 하나의 발주계획 전부를 한 번에 받지 않는다. */
const PLAN_PAGE_SIZE = 50;
/** 실행 목록 조회 상한. 범위 밖은 0이 아니라 미확인이며 그 사실을 화면이 적는다. */
const EXECUTION_LIST_LIMIT = 50;

const PURPOSE_LABEL: Readonly<Record<OrderPlanScreeningExecutionPurpose, string>> = {
  operational: "운영",
  gate_measurement: "측정 전용",
};

/** 계약 토큰은 그대로 두고 의미색이 붙는 한글 라벨을 함께 보인다. */
const ATTEMPT_STATUS_LABEL: Readonly<Record<OrderPlanScreeningAttemptStatus, string>> = {
  running: "실행 중",
  success: "성공",
  failed: "실패",
  rejected: "거부",
};

const VALIDATION_LABEL: Readonly<Record<OrderPlanArtifactValidationStatus, string>> = {
  pending: "대기",
  valid: "통과",
  invalid: "실패",
};

function mono(value: string, key: string) {
  return <span className="rs-mono" key={key}>{value}</span>;
}

/** 서버가 값을 주지 않은 측정값. 0으로도 성공으로도 바꾸지 않는다. */
function metric(value: number | null | undefined): string {
  return value === null || value === undefined ? "미측정" : value.toLocaleString("ko-KR");
}

function score(value: number | null | undefined): string {
  return value === null || value === undefined
    ? "미측정"
    : value.toLocaleString("ko-KR", { maximumFractionDigits: 4 });
}

function moment(value: string | null | undefined): string {
  return value ? formatDateTime(value) : "기록 없음";
}

function textValue(value: string | null | undefined, fallback = "미제공"): string {
  return value && value.trim() ? value : fallback;
}

/**
 * 실행 목록 순서. 서버 순서를 가정하지 않고 대기 시각 내림차순으로 고정한다
 * (동률은 실행 ID 내림차순). 기본 선택은 이 순서의 첫 행 = 가장 최근 실행이다.
 */
function sortExecutions(
  items: readonly OrderPlanScreeningExecutionSummary[],
): OrderPlanScreeningExecutionSummary[] {
  return [...items].sort((left, right) =>
    right.queued_at.localeCompare(left.queued_at)
    || right.execution_id.localeCompare(left.execution_id));
}

function purposeCell(purpose: OrderPlanScreeningExecutionPurpose) {
  // 경고 ②: 측정 전용 실행을 운영 판정처럼 보이게 하지 않는다.
  if (purpose === "gate_measurement") {
    return (
      <StatusToken
        label={PURPOSE_LABEL.gate_measurement}
        description="품질 게이트 측정 전용 실행입니다. 운영 판정이 아닙니다."
      />
    );
  }
  return <span>{PURPOSE_LABEL.operational}</span>;
}

export function OrderPlanScreeningPanel({
  runId,
  selectedExecutionId,
  onSelectExecution,
}: {
  runId: string;
  /** URL `execution=`. 이 회차의 실행이 아니면 무시하고 가장 최근 실행을 고른다. */
  selectedExecutionId: string | null;
  onSelectExecution: (executionId: string) => void;
}) {
  const [planOffset, setPlanOffset] = useState(0);

  const executionsQuery = useQuery({
    queryKey: ["order-plan-screening", "run-executions", runId],
    queryFn: ({ signal }) => api.getOrderPlanScreeningExecutions(
      { source_run_id: runId, limit: EXECUTION_LIST_LIMIT, offset: 0 },
      { signal },
    ),
    staleTime: 15_000,
  });

  const executions = useMemo(
    () => sortExecutions(executionsQuery.data?.items ?? []),
    [executionsQuery.data],
  );
  const activeExecution = executions.find((item) => item.execution_id === selectedExecutionId)
    ?? executions[0]
    ?? null;
  const activeExecutionId = activeExecution?.execution_id ?? null;
  const executionTotal = executionsQuery.data?.total ?? null;

  const detailQuery = useQuery({
    queryKey: ["order-plan-screening", "run-execution-detail", activeExecutionId],
    queryFn: ({ signal }) => api.getOrderPlanScreeningExecution(activeExecutionId as string, { signal }),
    enabled: Boolean(activeExecutionId),
    staleTime: 15_000,
    // 조회 실패를 조용히 되풀이하지 않는다. 목록은 남기고 상세 자리에만 알린다.
    retry: false,
  });

  const plansQuery = useQuery({
    queryKey: ["order-plan-screening", "run-plans", runId, planOffset],
    queryFn: ({ signal }) => api.getOrderPlans(
      { source_run_id: runId, limit: PLAN_PAGE_SIZE, offset: planOffset },
      { signal },
    ),
    enabled: Boolean(activeExecutionId),
    staleTime: 15_000,
  });

  // 회차를 바꾸면 계획 페이지를 처음으로 되돌린다.
  useEffect(() => setPlanOffset(0), [runId]);

  const detail = detailQuery.data ?? null;
  const planItems: OrderPlanListItem[] = plansQuery.data?.items ?? [];
  const planTotal = plansQuery.data?.total ?? null;
  const planScope = plansQuery.data?.scope ?? null;
  /**
   * 계획별 신호는 회차 기준 목록이다. 서버는 그 회차의 최신 완료 실행 하나를
   * 투영하므로 고른 실행과 다를 수 있다. 다르면 그 사실을 적고 같은 실행의
   * 값처럼 보이게 하지 않는다.
   */
  const planScopeExecutionId = planScope?.mode === "run" ? planScope.execution_id : null;
  const planScopeDiffers = Boolean(
    activeExecutionId && planScopeExecutionId && planScopeExecutionId !== activeExecutionId,
  );

  return (
    <>
      <Section
        title={`이 회차의 선별 실행${executionsQuery.data ? ` · ${formatNumber(executions.length)}건` : ""}`}
        action={executionsQuery.data || executionsQuery.error ? (
          <Button
            label="실행 목록 새로고침"
            size="sm"
            variant="ghost"
            onClick={() => { void executionsQuery.refetch(); }}
          />
        ) : undefined}
      >
        {executionsQuery.isPending ? (
          <Caption>선별 실행 목록을 불러오는 중입니다.</Caption>
        ) : null}
        {executionsQuery.error ? (
          <Note title="선별 실행 목록을 불러오지 못했습니다" tone="error">
            조회 실패는 실행 0건이 아닙니다. 이 회차의 선별 실행 유무는 미확인입니다.
          </Note>
        ) : null}
        {!executionsQuery.isPending && !executionsQuery.error && executions.length === 0 ? (
          <Caption>
            조회 범위 안에 이 회차의 발주계획 선별 실행이 없습니다. 조회 범위 밖은 미확인이며
            실행이 없었다는 뜻이 아닙니다.
          </Caption>
        ) : null}
        {executions.length ? (
          <>
            <DataTable
              caption="이 회차의 발주계획 선별 실행"
              headings={["실행 ID", "목적", "상태", "정책 버전", "끝난 시각"]}
              rows={executions.map((execution) => ({
                id: execution.execution_id,
                cells: [
                  <Button
                    key="pick"
                    className="rs-exec-pick"
                    label={execution.execution_id}
                    size="sm"
                    variant="ghost"
                    aria-pressed={execution.execution_id === activeExecutionId}
                    onClick={() => onSelectExecution(execution.execution_id)}
                  />,
                  purposeCell(execution.purpose),
                  <StatusToken
                    key="status"
                    label={execution.status}
                    description="발주계획 선별 실행의 상태입니다. 수집 회차의 상태와 다릅니다."
                  />,
                  mono(execution.policy_version, "policy"),
                  execution.finished_at ? formatDateTime(execution.finished_at) : "종료 기록 없음",
                ],
              }))}
            />
            {executionTotal !== null && executionTotal > executions.length ? (
              <Caption>
                {`조회 범위 ${formatNumber(executions.length)}건 / 전체 ${formatNumber(executionTotal)}건 · 범위 밖은 미확인입니다.`}
              </Caption>
            ) : null}
          </>
        ) : null}
      </Section>

      {detailQuery.error ? (
        <Note title="선택한 실행의 상세를 불러오지 못했습니다" tone="error" action={(
          <Button label="다시 시도" size="sm" onClick={() => { void detailQuery.refetch(); }} />
        )}>
          실행 목록은 그대로 남겨 둡니다. 배치별 기록과 산출물 요약은 미확인이며 없음이 아닙니다.
        </Note>
      ) : null}

      {activeExecution ? (
        <>
          <Section title="실행 기준">
            <Facts
              items={[
                ["실행 ID", mono(activeExecution.execution_id, "exec")],
                ["요청 ID", mono(activeExecution.request_id, "request")],
                ["실행 목적", purposeCell(activeExecution.purpose)],
                ["요청자", textValue(activeExecution.requested_by, "미확인")],
                ["정책 버전", mono(activeExecution.policy_version, "policy")],
                ["대상 건수", `${formatNumber(activeExecution.population_count)}건`],
                ["대상 식별 해시", mono(activeExecution.population_sha256, "population")],
                ["정책 식별 해시", mono(activeExecution.policy_sha256, "policy-sha")],
                [
                  "모델 연결 상태",
                  activeExecution.execution_allowed ? "허용됨" : "허용됨이 아님",
                ],
                ["모델 연결 식별 해시", mono(activeExecution.binding_sha256, "binding")],
                [
                  "1차 선별(BM25) 모델 연결",
                  <span key="stage1">
                    {activeExecution.stage1_binding_version}
                    {" · "}
                    {mono(activeExecution.stage1_binding_sha256, "stage1-sha")}
                  </span>,
                ],
                [
                  "모델 판단(Qwen) 모델 연결",
                  <span key="stage2">
                    {activeExecution.stage2_binding_version}
                    {" · "}
                    {mono(activeExecution.stage2_binding_sha256, "stage2-sha")}
                  </span>,
                ],
                ["수집 회차", mono(activeExecution.source_run_id, "source-run")],
                ["대기 시각", moment(activeExecution.queued_at)],
                ["시작 시각", moment(activeExecution.started_at)],
                ["마지막 heartbeat", moment(activeExecution.heartbeat_at)],
                ["끝난 시각", moment(activeExecution.finished_at)],
              ]}
            />
          </Section>

          <Section title="집계">
            <Facts
              items={[
                ["후보", formatNumber(activeExecution.counts.candidate_count)],
                ["완료", formatNumber(activeExecution.counts.completed_count)],
                ["실패", formatNumber(activeExecution.counts.failure_count)],
                ["1차 선정", formatNumber(activeExecution.counts.stage1_selected_count)],
                ["1차 탈락", formatNumber(activeExecution.counts.stage1_filtered_out_count)],
                ["1차 실패", formatNumber(activeExecution.counts.stage1_failed_count)],
                ["모델 관련", formatNumber(activeExecution.counts.stage2_relevant_count)],
                ["모델 비관련", formatNumber(activeExecution.counts.stage2_not_relevant_count)],
                ["모델 판단 보류", formatNumber(activeExecution.counts.stage2_uncertain_count)],
                ["모델 실패", formatNumber(activeExecution.counts.stage2_failed_count)],
                ["모델 거부", formatNumber(activeExecution.counts.stage2_rejected_count)],
                ["사람 검토", formatNumber(activeExecution.counts.human_review_count)],
              ]}
            />
            <Caption>
              후보·완료·실패는 이 실행이 시도한 건수입니다. 수집 건수나 판정 대상 전체와 같은
              값이 아닙니다.
            </Caption>
          </Section>

          <Section title="배치별 기록">
            {detailQuery.isPending ? (
              <Caption>배치별 기록을 불러오는 중입니다.</Caption>
            ) : null}
            {detail && detail.attempts.length === 0 ? (
              <Caption>서버가 이 실행의 배치 기록을 주지 않았습니다. 0건이 아니라 기록 없음입니다.</Caption>
            ) : null}
            {detail && detail.attempts.length ? (
              <DataTable
                caption="배치별 모델 호출 기록"
                headings={[
                  "배치 · 시도",
                  "모델 / revision",
                  "프롬프트 · 프로필 · 생성 설정",
                  "상태",
                  "실패 사유",
                  "토큰 입력 / 캐시 / 출력 / 합계",
                  "소요(ms)",
                  "시각",
                ]}
                rows={detail.attempts.map((attempt) => {
                  const failed = attempt.attempt_status === "failed" || attempt.attempt_status === "rejected";
                  const absent = failed ? "미제공" : "없음";
                  return {
                    id: attempt.attempt_id,
                    cells: [
                      <span className="rs-cell" key="batch">
                        {mono(attempt.batch_id, "batch-id")}
                        <span className="rs-row-sub">{`시도 ${formatNumber(attempt.attempt_no)} · 순서 ${formatNumber(attempt.sequence)}`}</span>
                      </span>,
                      <span className="rs-cell" key="model">
                        {attempt.model_name}
                        <span className="rs-row-sub">{mono(attempt.model_digest, "model-digest")}</span>
                      </span>,
                      <span className="rs-cell" key="inputs">
                        {attempt.prompt_version}
                        <span className="rs-row-sub">{mono(attempt.prompt_sha256, "prompt-sha")}</span>
                        {attempt.company_profile_version}
                        <span className="rs-row-sub">{mono(attempt.company_profile_sha256, "profile-sha")}</span>
                        <span className="rs-row-sub">{mono(attempt.generation_config_sha256, "generation-sha")}</span>
                      </span>,
                      <span className="rs-cell" key="status">
                        <StatusToken label={ATTEMPT_STATUS_LABEL[attempt.attempt_status]} />
                        <span className="rs-row-sub">{mono(attempt.attempt_status, "status-token")}</span>
                      </span>,
                      <span className="rs-cell" key="failure">
                        {attempt.failure_type ?? absent}
                        <span className="rs-row-sub">{attempt.failure_code ?? absent}</span>
                      </span>,
                      <span className="rs-mono" key="tokens">
                        {`${metric(attempt.input_tokens)} / ${metric(attempt.cached_input_tokens)} / ${metric(attempt.output_tokens)} / ${metric(attempt.total_tokens)}`}
                      </span>,
                      <span className="rs-mono" key="duration">{metric(attempt.duration_ms)}</span>,
                      <span className="rs-cell" key="moment">
                        {moment(attempt.started_at)}
                        <span className="rs-row-sub">{moment(attempt.finished_at)}</span>
                      </span>,
                    ],
                  };
                })}
              />
            ) : null}
            <Facts
              items={[
                [
                  "부분 산출물",
                  activeExecution.partial_artifact
                    ? <StatusToken key="partial" label="있음" description="일부 결과만 남은 실행입니다. 완전한 성공으로 읽지 않습니다." />
                    : "없음",
                ],
                ["오류 코드", activeExecution.error_code === null ? "서버 미제공" : mono(activeExecution.error_code, "error-code")],
              ]}
            />
            <Caption>
              부분 산출물과 오류 코드는 배치가 아니라 실행 단위 값입니다. 부분 산출물이 있으면
              일부 결과만 남았다는 뜻이며 성공으로 승격하지 않습니다.
            </Caption>
          </Section>

          <Section title="산출물 요약">
            {detailQuery.isPending ? <Caption>산출물 요약을 불러오는 중입니다.</Caption> : null}
            {detail && detail.artifacts.length === 0 ? (
              <Caption>서버가 이 실행의 산출물 요약을 주지 않았습니다.</Caption>
            ) : null}
            {detail && detail.artifacts.length ? (
              <DataTable
                caption="이 실행이 남긴 산출물"
                headings={["산출물", "검증 상태", "크기(bytes)", "식별 해시(sha256)"]}
                rows={detail.artifacts.map((artifact) => ({
                  id: `${artifact.kind}-${artifact.sha256}`,
                  cells: [
                    <span className="rs-cell" key="kind">
                      {mono(artifact.kind, "kind")}
                      <span className="rs-row-sub">{`${artifact.artifact_schema_version} · 객체 버전 ${textValue(artifact.object_version, "미제공")} · ${moment(artifact.created_at)}`}</span>
                    </span>,
                    <span className="rs-cell" key="validation">
                      <StatusToken label={VALIDATION_LABEL[artifact.validation_status]} />
                      <span className="rs-row-sub">{mono(artifact.validation_status, "validation-token")}</span>
                    </span>,
                    <span className="rs-mono" key="bytes">{formatNumber(artifact.byte_count)}</span>,
                    mono(artifact.sha256, "sha"),
                  ],
                }))}
              />
            ) : null}
            <Caption>본문·원문 경로·다운로드 URL은 이 화면에서 노출하지 않습니다.</Caption>
          </Section>

          <Section title="계획별 신호">
            <Caption>
              {`이 표는 수집 회차 ${runId} 기준입니다. 서버는 회차마다 완료된 최신 실행 하나를 계획별로 투영합니다.`}
            </Caption>
            {planScopeDiffers && planScopeExecutionId ? (
              <Note title="고른 실행과 계획별 신호의 기준 실행이 다릅니다" tone="warning">
                {`계획별 신호는 실행 ${planScopeExecutionId}의 결과입니다. 위에서 고른 실행의 계획별 결과가 아닙니다.`}
              </Note>
            ) : null}
            {plansQuery.data && planScope === null ? (
              <Caption>이 회차에는 완료된 선별 실행이 없어 계획별 신호가 투영되지 않았습니다.</Caption>
            ) : null}
            {plansQuery.isPending ? <Caption>계획별 신호를 불러오는 중입니다.</Caption> : null}
            {plansQuery.error ? (
              <Note title="계획별 신호를 불러오지 못했습니다" tone="error" action={(
                <Button label="다시 시도" size="sm" onClick={() => { void plansQuery.refetch(); }} />
              )}>
                조회 실패는 계획 0건이 아닙니다.
              </Note>
            ) : null}
            {plansQuery.data && planItems.length === 0 ? (
              <Caption>이 회차의 발주계획이 조회 범위 안에 없습니다.</Caption>
            ) : null}
            {planItems.length ? (
              <>
                <DataTable
                  caption="이 회차의 계획별 선별 신호"
                  headings={[
                    "발주계획",
                    "1차 상태",
                    "순위",
                    "점수",
                    "모델 처리 상태",
                    "모델 판단",
                    "모델 점수",
                    "가까운 회사 역량",
                    "판단 근거",
                    "관측 시각",
                  ]}
                  rows={planItems.map((item) => ({
                    id: String(item.order_plan_pk),
                    cells: [
                      <span className="rs-cell" key="plan">
                        {textValue(item.title, "제목 미제공")}
                        <span className="rs-row-sub">{mono(item.order_plan_unty_no, "unty")}</span>
                        {item.source_run_id && item.source_run_id !== runId ? (
                          <span className="rs-row-sub">{`수집 회차 ${item.source_run_id}`}</span>
                        ) : null}
                        <Link
                          className="rs-inline-link"
                          to={`/order-plans?qwen=&source_run_id=${encodeURIComponent(runId)}&selected=${item.order_plan_pk}`}
                          aria-label={`${textValue(item.title, "제목 미제공")} 실무 화면에서 보기`}
                        >
                          실무 화면에서 보기
                        </Link>
                      </span>,
                      item.stage1_status === null ? "판정 없음" : mono(item.stage1_status, "stage1"),
                      <span className="rs-mono" key="rank">{metric(item.stage1_rank)}</span>,
                      <span className="rs-mono" key="score">{score(item.stage1_score)}</span>,
                      item.stage2_status === null ? "판정 없음" : mono(item.stage2_status, "stage2"),
                      item.qwen_relevance === null ? "판정 없음" : mono(item.qwen_relevance, "relevance"),
                      <span className="rs-mono" key="qwen-score">{score(item.qwen_score)}</span>,
                      textValue(item.nearest_capability),
                      textValue(item.qwen_reason, "근거 미제공"),
                      moment(item.observed_at),
                    ],
                  }))}
                />
                <div className="rs-row rs-spread">
                  <Caption as="span">
                    {planTotal === null
                      ? `${formatNumber(planOffset + 1)}–${formatNumber(planOffset + planItems.length)} / 전체 미확인`
                      : `${formatNumber(planOffset + 1)}–${formatNumber(planOffset + planItems.length)} / ${formatNumber(planTotal)}`}
                  </Caption>
                  <span className="rs-detail-actions">
                    <Button
                      label="이전 50건"
                      size="sm"
                      variant="secondary"
                      isDisabled={planOffset === 0 || plansQuery.isFetching}
                      onClick={() => setPlanOffset((current) => Math.max(0, current - PLAN_PAGE_SIZE))}
                    />
                    <Button
                      label="다음 50건"
                      size="sm"
                      variant="secondary"
                      isDisabled={
                        plansQuery.isFetching
                        || planTotal === null
                        || planOffset + planItems.length >= planTotal
                      }
                      onClick={() => setPlanOffset((current) => current + PLAN_PAGE_SIZE)}
                    />
                  </span>
                </div>
              </>
            ) : null}
            <Caption>
              `판정 없음`은 비관련이 아닙니다. 1차 상태·모델 판단은 서버가 준 계약 값 그대로이며
              실무 화면의 한글 라벨과 같은 값을 가리킵니다.
            </Caption>
          </Section>
        </>
      ) : null}

      {!activeExecution && !executionsQuery.isPending && !executionsQuery.error ? (
        <Text as="p">고를 수 있는 발주계획 선별 실행이 없어 실행 기준·배치 기록을 보일 수 없습니다.</Text>
      ) : null}
    </>
  );
}
