import { Button } from "@astryxdesign/core/Button";
import { Selector } from "@astryxdesign/core/Selector";
import { Text } from "@astryxdesign/core/Text";
import type {
  ScreeningExecutionDetailResponse,
  ScreeningExecutionResponse,
  ScreeningStatus,
} from "../../lib/types";
import { formatDateTime, present } from "../../lib/format";
import { Caption, DataTable, Facts, Note, Section, StatusToken } from "./RunStatusPrimitives";
import {
  countLabel,
  isScreeningTerminal,
  progressPercent,
  remainingCount,
  stageLabels,
} from "./runStatusData";

interface ScreeningRunPanelProps {
  runId: string;
  /** 조회 범위 안의 이 회차 전량 판정 실행. 범위 밖은 이 목록에 없다. */
  executions: ScreeningExecutionResponse[];
  selectedExecutionId: string | null;
  onSelectExecution: (executionId: string) => void;
  execution: ScreeningExecutionDetailResponse | null;
  executionSummary: ScreeningExecutionResponse | null;
  executionLoading: boolean;
  executionError: unknown;
  listLoading: boolean;
  listError: unknown;
  listReady: boolean;
  listRefreshing: boolean;
  onRetryList: () => void;
  onOpenPublishedRun: (runId: string) => void;
  publishedRunNavigationBusy: boolean;
  publishedRunNavigationError: string | null;
  /** 새 실행을 막는 이유. 핵심 건수 아래에 둔다(첫 화면을 밀지 않는다). */
  blockedReason?: string | null;
  /** 회차 목록 최신화 실패. 마찬가지로 건수 아래에 둔다. */
  listRefreshWarning?: string | null;
}

const statusLabels: Record<ScreeningStatus, string> = {
  대기: "대기 중",
  "실행 중": "실행 중",
  "중지 요청": "중지 요청",
  성공: "성공",
  "부분 성공": "부분 성공",
  실패: "실패",
  중단됨: "중단됨",
};

export function screeningStatusLabel(status: ScreeningStatus | undefined | null): string {
  return status ? statusLabels[status] ?? "상태 미확인" : "상태 미확인";
}

const artifactLinks: Array<{ key: "decisions" | "failures" | "telemetry" | "screening_result"; label: string }> = [
  { key: "decisions", label: "판정 결과" },
  { key: "failures", label: "실패 목록" },
  { key: "telemetry", label: "실행 관측" },
  { key: "screening_result", label: "통합 결과" },
];

/**
 * 진행 현황 탭의 판정 실행 구역.
 *
 * 회차 상태와 판정 실행 상태를 구분한다. 회차 목록의 상태가 이 구역의 상태를
 * 대신하지 않으며, 조회 범위 밖 실행은 "미확인"으로 남는다. 진행률의 분모가
 * 없으면 백분율을 만들지 않는다.
 */
export function ScreeningRunPanel({
  runId,
  executions,
  selectedExecutionId,
  onSelectExecution,
  execution,
  executionSummary,
  executionLoading,
  executionError,
  listLoading,
  listError,
  listReady,
  listRefreshing,
  onRetryList,
  onOpenPublishedRun,
  publishedRunNavigationBusy,
  publishedRunNavigationError,
  blockedReason = null,
  listRefreshWarning = null,
}: ScreeningRunPanelProps) {
  const detailExecution = execution && execution.execution_id === selectedExecutionId ? execution : null;
  const current = detailExecution ?? executionSummary;
  const status = current?.status;
  const percent = progressPercent(current);
  const remaining = remainingCount(current);
  const processed = current ? current.completed_count + current.failure_count : null;

  return (
    <Section
      title="전체 후보 판정 실행"
      action={current ? <StatusToken label={screeningStatusLabel(status)} /> : <Caption as="span">실행 기록 없음</Caption>}
    >
      {listLoading ? (
        <Caption>이 회차의 판정 실행 목록을 불러오는 중입니다. 목록 확인 전에는 새 실행을 시작할 수 없습니다.</Caption>
      ) : null}
      {listError ? (
        <div className="rs-inline-error" role="alert" aria-live="assertive" aria-busy={listRefreshing}>
          <Text as="span">판정 실행 기록을 불러오지 못했습니다. 상태는 미확인이며 0건이 아닙니다.</Text>
          <Button
            label={listRefreshing ? "다시 확인 중…" : "다시 시도"}
            size="sm"
            isDisabled={listRefreshing}
            onClick={onRetryList}
          />
        </div>
      ) : null}

      {!current && listReady && !listError ? (
        <Note title="이 회차에는 조회 범위 안의 전량 판정 실행이 없습니다">
          범위 밖에 실행이 있을 수 있습니다. 없음을 실행 0건이나 성공으로 읽지 않습니다.
        </Note>
      ) : null}
      {/* 실행이 없어 아래 본문이 그려지지 않는 상태에서도 안내는 남는다. */}
      {!current && blockedReason ? (
        <Note title={blockedReason} tone="warning">
          회차 상태와 판정 실행 상태, 결과 게시와 품질 표식은 각각 별도입니다.
        </Note>
      ) : null}
      {!current && listRefreshWarning ? <Caption>{listRefreshWarning}</Caption> : null}

      {current ? (
        <>
          <div
            className="rs-progress-track"
            role="progressbar"
            aria-label="판정 처리 비율"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={percent ?? undefined}
            aria-valuetext={percent === null ? "진행률 계산 불가" : `${percent}%`}
          >
            {percent === null ? null : <div className="rs-progress-value" style={{ width: `${percent}%` }} />}
          </div>
          <div className="rs-row rs-spread">
            <Caption as="span">
              {processed === null || typeof current.candidate_count !== "number"
                ? "처리 건수 미확인"
                : `${processed.toLocaleString("ko-KR")} / ${current.candidate_count.toLocaleString("ko-KR")}건 처리`}
            </Caption>
            <Caption as="span">{percent === null ? "진행률 계산 불가" : `${percent}%`}</Caption>
          </div>

          <div className="rs-stat-line">
            <div>
              <Caption as="span">판정 대상</Caption>
              <Text className="rs-stat-value" as="span">{countLabel(current.candidate_count)}</Text>
            </div>
            <div>
              <Caption as="span">완료</Caption>
              <Text className="rs-stat-value" as="span">{countLabel(current.completed_count)}</Text>
            </div>
            <div>
              <Caption as="span">실패</Caption>
              <Text className="rs-stat-value" as="span">{countLabel(current.failure_count)}</Text>
            </div>
            <div>
              <Caption as="span">{isScreeningTerminal(status) ? "미처리" : "남은 대상"}</Caption>
              <Text className="rs-stat-value" as="span">{countLabel(remaining)}</Text>
            </div>
          </div>

          {/* 여기부터는 첫 화면 아래다. 실행 선택기와 안내 문구는 없애지 않고
            * 핵심 건수 뒤로 옮긴다. */}
          {blockedReason ? (
            <Note title={blockedReason} tone="warning">
              회차 상태와 판정 실행 상태, 결과 게시와 품질 표식은 각각 별도입니다.
            </Note>
          ) : null}
          {listRefreshWarning ? <Caption>{listRefreshWarning}</Caption> : null}

          {executions.length > 1 ? (
            <details className="rs-disclosure">
              <summary>다른 판정 실행 확인 · 조회 범위 안 {executions.length}건</summary>
              <Selector
                label="확인할 판정 실행"
                size="sm"
                value={selectedExecutionId ?? undefined}
                onChange={onSelectExecution}
                options={executions.map((item) => ({
                  value: item.execution_id,
                  label: `#${item.queue_no} · ${screeningStatusLabel(item.status)} · ${formatDateTime(item.queued_at)}`,
                }))}
              />
            </details>
          ) : null}

          <Facts
            items={[
              ["처리 단계", current.current_stage ? stageLabels[current.current_stage] ?? "단계 미확인" : isScreeningTerminal(status) ? "실행 종결" : "대기 중"],
              ["대기 순번", status === "대기" && current.queue_position !== null ? `${current.queue_position}번` : "해당 없음"],
              ["현재 공고", <span className="rs-mono" key="notice">{present(current.current_notice_id, "없음")}</span>],
              ["실행 담당자", present(current.requested_by, "담당자 미확인")],
              ["대기열 등록", formatDateTime(current.queued_at)],
              ["종료", current.finished_at ? formatDateTime(current.finished_at) : "종결 전"],
            ]}
          />

          {executionLoading ? <Caption>실행 상세를 갱신하는 중입니다.</Caption> : null}
          {executionError ? (
            <Caption>실행 상세를 갱신하지 못했습니다. 자동 갱신을 계속 시도하며 표시된 값은 마지막으로 받은 값입니다.</Caption>
          ) : null}

          {current.status === "중지 요청" ? (
            <Note title="중지 요청을 기록했습니다" tone="warning" role="status">
              현재 모델 호출이 끝난 뒤 다음 공고를 시작하지 않고 중단됩니다. 완료된 결과는 삭제되지 않습니다.
            </Note>
          ) : null}
          {current.failure_count > 0 ? (
            <Note title={`실패 ${current.failure_count.toLocaleString("ko-KR")}건의 확인이 필요합니다`} tone="warning">
              실패한 항목은 성공 건수와 구분해 기록합니다. 실패 내역 탭에서 확인합니다.
            </Note>
          ) : null}
          {current.status === "실패" ? (
            <Note title="판정 실행이 실패로 종결됐습니다" tone="error" role="note">
              {present(current.error_summary, "서버가 실패 사유를 남기지 않았습니다.")}
            </Note>
          ) : null}
          {current.status === "중단됨" ? (
            <Note title="실행이 중단되어 미처리 항목이 남았습니다">
              기존 실행 기록을 보존하며 자동으로 다시 시작하지 않습니다.
              {current.stop_requested_by ? ` 중지 요청 담당자 ${current.stop_requested_by}.` : ""}
            </Note>
          ) : null}

          <Section title="원본 회차와 게시 결과">
            <DataTable
              caption="원본 회차와 게시된 파생 회차"
              headings={["구분", "회차", "뜻"]}
              rows={[
                {
                  id: "source",
                  cells: [
                    "원본 회차",
                    <span className="rs-mono" key="source">{runId}</span>,
                    "수집·기존 판정을 덮어쓰지 않습니다",
                  ],
                },
                {
                  id: "published",
                  cells: [
                    "게시된 파생 회차",
                    current.published_run_id
                      ? <span className="rs-mono" key="published">{current.published_run_id}</span>
                      : "없음",
                    current.published_run_id ? "새 판정 결과가 이 회차에 게시됐습니다" : "게시 전이거나 게시하지 않았습니다",
                  ],
                },
              ]}
            />
            {current.published_run_id ? (
              <div className="rs-link-row">
                <Button
                  label={publishedRunNavigationBusy ? "파생 회차 확인 중…" : "파생 회차로 이동"}
                  size="sm"
                  isDisabled={publishedRunNavigationBusy}
                  onClick={() => onOpenPublishedRun(current.published_run_id as string)}
                />
                {detailExecution?.result_urls.published_run ? (
                  <a href={detailExecution.result_urls.published_run} target="_blank" rel="noreferrer">게시 결과 링크 열기</a>
                ) : null}
              </div>
            ) : null}
            {publishedRunNavigationError && current.published_run_id ? (
              <div className="rs-inline-error" role="alert" aria-live="assertive">
                <Text as="span">{publishedRunNavigationError}</Text>
                <Button
                  label={publishedRunNavigationBusy ? "다시 확인 중…" : "다시 시도"}
                  size="sm"
                  isDisabled={publishedRunNavigationBusy}
                  onClick={() => onOpenPublishedRun(current.published_run_id as string)}
                />
              </div>
            ) : null}
          </Section>

          {detailExecution ? (
            <Section title="안전한 산출물 링크" action={<Caption as="span">서버가 준 경로만 엽니다</Caption>}>
              <div className="rs-link-row">
                {artifactLinks.map(({ key, label }) => detailExecution.result_urls[key]
                  ? <a href={detailExecution.result_urls[key] as string} key={key} target="_blank" rel="noreferrer">{label}</a>
                  : null)}
                {!artifactLinks.some(({ key }) => Boolean(detailExecution.result_urls[key]))
                  ? <Caption as="span">사용 가능한 산출물 링크가 없습니다.</Caption>
                  : null}
              </div>
            </Section>
          ) : null}

          <Caption>
            처리 완료와 품질 검증은 별도입니다. 이 실행 API는 품질 표식(quality_status)을 제공하지
            않으므로 화면은 측정 통과·참조 실행·mock 참조 어느 쪽도 주장하지 않습니다.
          </Caption>
        </>
      ) : null}
    </Section>
  );
}
