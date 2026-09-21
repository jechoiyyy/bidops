import { useState } from "react";
import { useQueries, useQuery, type UseQueryResult } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { Button } from "@astryxdesign/core/Button";
import { Selector } from "@astryxdesign/core/Selector";
import { Text } from "@astryxdesign/core/Text";
import {
  CancelButton,
  CriteriaDialog,
  DataTable,
  DetailFooter,
  DetailHeader,
  DialogActions,
  Disclosure,
  Facts,
  Note,
  Queue,
  Section,
  Small,
  StatLine,
  StateView,
} from "../components/criteria/CriteriaPrimitives";
import { ApiError, api } from "../lib/api";
import { formatNumber, formatRunRange, runStatusLabel } from "../lib/format";
import { runOptionLabel } from "../lib/runOptions";
import type { RunSummary, ValidationMetric, ValidationMetricsResponse } from "../lib/types";

/**
 * 검증 지표 탭.
 *
 * 서버가 돌려준 key·label·value·threshold·basis·reason을 그대로 보여 준다. 화면이
 * 지표 이름이나 값을 만들지 않고, 계산 불가·미확인·실제 0을 서로 다르게 적는다.
 *
 * **회차별 추이의 조회 범위를 제한한다.** 이전 구현은 회차 목록 전체를 돌며 회차마다
 * 지표를 한 번씩 더 조회해(`Promise.all`) 회차가 늘수록 요청이 선형으로 늘었고, 한
 * 회차만 실패해도 추이 전체를 버렸다. 지금은 **최근 회차 N개**만 조회하고 그 사실을
 * 화면이 밝히며, 실패한 회차만 미확인으로 남기고 나머지 값은 유지한다.
 */

// 상세에서 한눈에 비교할 수 있는 만큼만 조회한다. 이 수를 넘는 회차는 "조회 범위
// 밖"이며 값이 없다는 뜻이 아니다.
const HISTORY_LIMIT = 5;

function statusLabel(status: ValidationMetric["status"]): string {
  if (status === "pass") return "통과";
  if (status === "fail") return "미달";
  if (status === "measured") return "측정됨";
  return "계산 불가";
}

function thresholdLabel(threshold: unknown): string {
  if (threshold === null) return "사전 확정 임계값 없음";
  if (typeof threshold === "undefined") return "임계값 미확인";
  if (typeof threshold === "number" && Number.isFinite(threshold)) return `${Math.round(threshold * 100)}% 이상`;
  if (typeof threshold === "object" && threshold !== null && "min" in threshold && "max" in threshold) {
    const range = threshold as { min: unknown; max: unknown };
    if (typeof range.min === "number" && typeof range.max === "number" && Number.isFinite(range.min) && Number.isFinite(range.max)) {
      return `${Math.round(range.min * 100)}~${Math.round(range.max * 100)}%`;
    }
  }
  return "임계값 미확인";
}

function basisLabel(metric: ValidationMetric): string {
  const { numerator, denominator } = metric.basis;
  const numeratorLabel = typeof numerator === "number" && Number.isFinite(numerator) ? formatNumber(numerator) : "미확인";
  const denominatorLabel = typeof denominator === "number" && Number.isFinite(denominator) ? formatNumber(denominator) : "미확인";
  if (metric.status === "not_measurable") return `계산 대상 ${denominatorLabel}건 · 계산 불가`;
  return `${numeratorLabel} / ${denominatorLabel}건`;
}

function valueLabel(metric: ValidationMetric): string {
  if (metric.percentage === null) return metric.status === "not_measurable" ? "계산 불가" : "값 미확인";
  return `${metric.percentage.toFixed(1)}%`;
}

function detailValueLabel(value: unknown): string {
  if (value === null || value === undefined) return "미확인";
  if (typeof value === "object") return JSON.stringify(value) ?? "값 미기록";
  if (typeof value === "string" && value.trim() === "") return "값 미기록";
  return String(value);
}

function basisDetailEntries(metric: ValidationMetric): [string, string][] {
  return Object.entries(metric.basis.detail ?? {}).map(([key, value]) => [key, detailValueLabel(value)]);
}

/** 한 회차의 한 지표. 조회 실패·지표 없음·계산 불가·값 없음을 접지 않는다. */
type HistoryState = "measured" | "not_measurable" | "unknown" | "absent" | "failed";

function historyPoint(metrics: ValidationMetric[] | undefined, failed: boolean, key: string): { state: HistoryState; label: string } {
  if (failed) return { state: "failed", label: "조회 실패" };
  if (!metrics) return { state: "unknown", label: "미확인" };
  const metric = metrics.find((item) => item.key === key);
  if (!metric) return { state: "absent", label: "이 회차에 지표 없음" };
  if (metric.status === "not_measurable") return { state: "not_measurable", label: "계산 불가" };
  if (metric.percentage === null) return { state: "unknown", label: "값 미확인" };
  return { state: "measured", label: `${metric.percentage.toFixed(1)}%` };
}

function runLabel(run: RunSummary): string {
  return formatRunRange(run.run_id, run.window_from, run.window_to);
}

function queryErrorText(error: unknown, resource: string): string {
  if (error instanceof ApiError && error.status > 0) return `${resource}을(를) 불러오지 못했습니다 (${error.status}).`;
  return `${resource}을(를) 불러오지 못했습니다.`;
}

export function MetricsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [runPickerOpen, setRunPickerOpen] = useState(false);
  const runsQuery = useQuery({ queryKey: ["runs"], queryFn: api.getRuns, staleTime: 30_000 });
  const runs = runsQuery.data?.items ?? [];

  const queryRunId = searchParams.get("run");
  // 수집·표본까지만 끝난 회차는 판정이 없어 지표가 비어 보인다. 명시적으로 고른
  // 회차가 없으면 판정을 갖춘 최신 회차를 기본으로 삼는다.
  const selectedRun = runs.find((run) => run.run_id === queryRunId)
    ?? runs.find((run) => run.counts.judgments > 0)
    ?? runs[0]
    ?? null;
  const selectedRunId = selectedRun?.run_id ?? null;

  // 조회 범위: 최근 회차 N개 + 담당자가 고른 회차. 목록 전체를 훑지 않는다.
  const windowRuns = runs.slice(0, HISTORY_LIMIT);
  const historyRuns = selectedRun && !windowRuns.some((run) => run.run_id === selectedRun.run_id)
    ? [selectedRun, ...windowRuns]
    : windowRuns;
  // 회차마다 독립된 query다. 하나가 실패해도 나머지 회차의 값은 그대로 남는다
  // (`Promise.all`은 한 회차의 실패로 추이 전체를 버렸다).
  const historyResults = useQueries({
    queries: historyRuns.map((run) => ({
      queryKey: ["validation-metrics", run.run_id] as const,
      queryFn: () => api.getValidationMetrics(run.run_id),
      staleTime: 10_000,
      retry: false,
    })),
  }) as UseQueryResult<ValidationMetricsResponse, unknown>[];
  const selectedIndex = historyRuns.findIndex((run) => run.run_id === selectedRunId);
  const selectedResult = selectedIndex >= 0 ? historyResults[selectedIndex] : undefined;
  const metrics = selectedResult?.data?.metrics ?? [];
  const failedHistory = historyResults.filter((result) => result.isError).length;
  // 아래의 이른 반환이 query 결과 union을 좁히지 못하도록 여기서 값으로 굳힌다.
  const selectedPending = selectedResult?.isPending ?? false;
  const selectedFailed = selectedResult?.isError ?? false;
  const selectedError: unknown = selectedResult?.error;
  const refetchSelected = () => { void selectedResult?.refetch(); };

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

  if (runsQuery.isPending || selectedPending) {
    return (
      <div className="crit-workspace" id="criteria-panel-metrics" role="tabpanel">
        <StateView description="회차와 지표 계산 결과를 확인하는 중입니다." kind="loading" title="검증 지표를 불러오는 중입니다" />
      </div>
    );
  }
  if (runsQuery.error) {
    return (
      <div className="crit-workspace" id="criteria-panel-metrics" role="tabpanel">
        <StateView
          action={<Button label="다시 조회" onClick={() => { void runsQuery.refetch(); }} />}
          description={queryErrorText(runsQuery.error, "회차 목록")}
          kind="error"
          title="회차 목록을 불러오지 못했습니다."
        />
      </div>
    );
  }
  if (!selectedRun) {
    return (
      <div className="crit-workspace" id="criteria-panel-metrics" role="tabpanel">
        <StateView
          description="판정이 적재된 회차가 생기면 검증 지표를 계산할 수 있습니다. 회차가 없는 것과 계산 실패는 다른 상태입니다."
          kind="empty"
          title="계산할 회차가 없습니다."
        />
      </div>
    );
  }

  const selectedMetricKey = searchParams.get("metric");
  const metric = metrics.find((item) => item.key === selectedMetricKey) ?? metrics[0] ?? null;
  const detailEntries = metric ? basisDetailEntries(metric) : [];

  return (
    <div className="crit-workspace" id="criteria-panel-metrics" role="tabpanel">
      <Queue
        count={selectedFailed ? null : metrics.length}
        emptyText={selectedFailed ? "지표를 불러오지 못했습니다. 0건이 아닙니다." : "이 회차에는 계산된 지표가 없습니다."}
        footer={`회차 ${selectedRun.run_id} · ${runLabel(selectedRun)}`}
        items={metrics.map((item) => ({
          id: item.key,
          title: item.label,
          subtitle: valueLabel(item),
          status: statusLabel(item.status),
          meta: `기준 · ${thresholdLabel(item.threshold)}`,
        }))}
        onSelect={(id) => updateParams({ metric: id })}
        selectedId={metric?.key ?? null}
        title="검증 지표 목록"
      />
      <section aria-label="선택한 검증 지표" className="crit-detail">
        {selectedFailed ? (
          <StateView
            action={<Button label="다시 조회" onClick={refetchSelected} />}
            description={`${queryErrorText(selectedError, "이 회차의 검증 지표")} 조회 실패를 0%나 계산 불가로 바꾸지 않습니다.`}
            kind="error"
            title="이 회차의 검증 지표를 불러오지 못했습니다."
          />
        ) : metric ? (
          <>
            <DetailHeader
              eyebrow={`검증 지표 · 선택 회차 ${runLabel(selectedRun)}`}
              status={statusLabel(metric.status)}
              title={metric.label}
            >
              <Small><code>{metric.key}</code></Small>
            </DetailHeader>
            <div className="crit-detail-scroll" id="criteria-metrics-detail">
              <StatLine items={[
                ["측정값", valueLabel(metric)],
                ["통과 기준", thresholdLabel(metric.threshold)],
                ["계산 근거", basisLabel(metric)],
              ]} />
              {metric.percentage === null ? (
                <Note role="status" title={metric.status === "not_measurable" ? "계산 불가" : "측정값이 없습니다"} tone="warning">
                  {`${metric.reason ?? "사유 미기록"} · 0%로 표시하지 않습니다.`}
                </Note>
              ) : null}
              <Section title="계산 근거">
                <Facts items={[
                  ["분자", typeof metric.basis.numerator === "number" ? formatNumber(metric.basis.numerator) : "미확인"],
                  ["분모", typeof metric.basis.denominator === "number" ? formatNumber(metric.basis.denominator) : "미확인"],
                  ["임계값 충족", metric.meets_threshold === null ? "판정 없음" : metric.meets_threshold ? "충족" : "미충족"],
                  ["설명", metric.reason ?? "설명 없음"],
                ]} />
                {detailEntries.length > 0 ? (
                  <Disclosure summary="세부 근거">
                    <DataTable
                      caption="세부 계산 근거"
                      headings={["항목", "값"]}
                      rows={detailEntries.map(([key, value]) => [<code key="k">{key}</code>, <Text key="v">{value}</Text>])}
                    />
                  </Disclosure>
                ) : null}
              </Section>
              <Section title={`회차별 값과 상태 · 최근 ${historyRuns.length}개 회차`}>
                <Small>
                  {`전체 회차 ${runs.length}개 가운데 최근 ${historyRuns.length}개만 조회합니다. 조회 범위 밖 회차의 값은 미확인이며 없음을 뜻하지 않습니다.`}
                </Small>
                {failedHistory > 0 ? (
                  <Note role="alert" title={`과거 회차 지표 ${failedHistory}건을 불러오지 못했습니다`} tone="warning">
                    실패한 회차만 조회 실패로 남기고 나머지 회차의 값과 계산 근거는 그대로 표시합니다.
                  </Note>
                ) : null}
                <DataTable
                  caption={`${metric.label}의 회차별 값`}
                  headings={["회차", "수집 기간", "측정값", "실행 상태"]}
                  rows={historyRuns.map((run, index) => {
                    const result = historyResults[index];
                    const point = historyPoint(result?.data?.metrics, Boolean(result?.isError), metric.key);
                    return [
                      <span className="crit-cell-stack" key="run">
                        <code>{run.run_id}</code>
                        {run.run_id === selectedRun.run_id ? <Small>선택한 회차</Small> : null}
                      </span>,
                      <Text key="range">{runLabel(run)}</Text>,
                      <Text key="value" weight={point.state === "measured" ? "semibold" : undefined}>{point.label}</Text>,
                      <Text key="status">{runStatusLabel(run.status)}</Text>,
                    ];
                  })}
                />
              </Section>
              <Note title="지표와 운영 승인은 구분합니다">
                이 회차의 수치가 좋아도 승인용 품질 게이트 통과를 대신하지 않습니다.
              </Note>
            </div>
            <DetailFooter note="측정하지 않은 값과 실제 0을 구분합니다. 조회 범위 밖은 미확인입니다.">
              <Button label="회차 선택" onClick={() => setRunPickerOpen(true)} size="sm" />
            </DetailFooter>
          </>
        ) : (
          <StateView
            action={<Button label="회차 선택" onClick={() => setRunPickerOpen(true)} />}
            description="다른 회차를 고르면 계산된 지표를 확인할 수 있습니다. 지표 없음과 계산 실패는 다른 상태입니다."
            kind="empty"
            title="이 회차에는 계산된 지표가 없습니다."
          />
        )}
      </section>
      <CriteriaDialog onClose={() => setRunPickerOpen(false)} open={runPickerOpen} title="검증 지표 대상 회차">
        <Selector
          hasSearch
          label="대상 회차"
          onChange={(value) => { updateParams({ run: value, metric: null }); setRunPickerOpen(false); }}
          options={runs.map((run) => ({
            // 라벨은 공용 회차 표기(U3)를 쓴다. 회차 식별자 원문은 줄이지 않고
            // 설명으로 내린다(`buildSourceRunOptions({ audience: "ops" })`와 같은 방식) —
            // 이 화면은 상태·판정 건수도 함께 골라야 하므로 그 값은 설명에 남긴다.
            value: run.run_id,
            label: runOptionLabel(run),
            description: `${run.run_id} · ${runStatusLabel(run.status)} · 판정 ${formatNumber(run.counts.judgments)}건`,
          }))}
          placeholder="회차를 선택하십시오"
          value={selectedRun.run_id}
        />
        <Small>{`조회한 회차 목록 ${runs.length}개 · 회차별 지표는 최근 ${HISTORY_LIMIT}개까지 함께 조회합니다.`}</Small>
        <DialogActions>
          <CancelButton label="닫기" onClick={() => setRunPickerOpen(false)} />
        </DialogActions>
      </CriteriaDialog>
    </div>
  );
}
