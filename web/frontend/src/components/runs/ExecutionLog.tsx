import { Text } from "@astryxdesign/core/Text";
import type { PipelineLogResponse } from "../../lib/types";
import { formatDateTime, present } from "../../lib/format";
import { Caption, DataTable, Section, StatusToken } from "./RunStatusPrimitives";

interface ExecutionLogProps {
  data: PipelineLogResponse | undefined;
  loading: boolean;
  error: unknown;
}

function stageLabel(stage: string): string {
  if (stage === "collect") return "수집";
  if (stage === "sample") return "표본 선정";
  if (stage === "report") return "보고 생성";
  return present(stage, "단계 미확인");
}

function statusLabel(status: string): string {
  if (status === "running") return "진행 중";
  if (status === "failed") return "실패";
  if (status === "pending") return "대기 중";
  if (status === "success") return "성공";
  return present(status, "상태 미확인");
}

/**
 * 실행 기록. 파이프라인 실행 이력과 로그 줄을 그대로 보여 준다.
 * 조회 실패를 "기록 없음"으로 바꾸지 않는다.
 */
export function ExecutionLog({ data, loading, error }: ExecutionLogProps) {
  const running = data?.executions.some((execution) => execution.status === "pending" || execution.status === "running");
  const executions = data?.executions ?? [];

  return (
    <Section
      title="파이프라인 실행 기록"
      action={
        <Caption as="span">
          {error ? "조회 실패 · 미확인" : running ? "실행 중 · 자동 갱신" : executions.length ? `${executions.length}회 실행 기록` : "실행 기록 없음"}
        </Caption>
      }
    >
      {loading && !data ? <Caption>로그를 불러오는 중입니다.</Caption> : null}
      {error ? (
        <div className="rs-inline-error" role="alert">
          <Text as="span">실행 로그를 불러오지 못했습니다. 기록이 없다는 뜻이 아닙니다.</Text>
        </div>
      ) : null}
      {executions.length > 0 ? (
        <DataTable
          caption="파이프라인 실행 이력"
          headings={["시각", "실행 내용", "상태"]}
          rows={executions.map((execution) => ({
            id: execution.execution_id,
            cells: [
              <span className="rs-mono" key="time">{formatDateTime(execution.started_at)}</span>,
              <span key="content">
                {stageLabel(execution.stage)}
                <span className="rs-row-sub">
                  <span className="rs-mono">{execution.execution_id}</span>
                  {execution.result_run_id ? ` · 파생 회차 ${execution.result_run_id}` : ""}
                  {execution.exit_code !== null ? ` · 종료 코드 ${execution.exit_code}` : ""}
                  {execution.error ? ` · ${execution.error}` : ""}
                </span>
              </span>,
              <StatusToken key="status" label={statusLabel(execution.status)} />,
            ],
          }))}
        />
      ) : null}
      {!loading && !error && executions.length === 0 ? <Caption>이 회차에 기록된 파이프라인 실행이 없습니다.</Caption> : null}

      {data?.items.length ? (
        <div className="rs-log-lines" aria-label="실행 로그" aria-live={running ? "polite" : "off"}>
          {data.items.map((line, index) => (
            <div className={`rs-log-line${line.level === "error" ? " rs-log-line-error" : ""}`} key={`${line.timestamp}-${index}`}>
              <time dateTime={line.timestamp}>{formatDateTime(line.timestamp)}</time>
              <span>{line.message}</span>
            </div>
          ))}
        </div>
      ) : null}
      {!loading && !error && data && data.items.length === 0 ? <Caption>아직 기록된 로그 줄이 없습니다.</Caption> : null}
    </Section>
  );
}
