import { useState } from "react";
import { Button } from "@astryxdesign/core/Button";
import { Dialog, DialogHeader } from "@astryxdesign/core/Dialog";
import { Text } from "@astryxdesign/core/Text";
import { ChevronRight } from "lucide-react";
import type {
  ScreeningAttemptResponse,
  ScreeningExecutionDetailResponse,
  ScreeningExecutionResponse,
  ScreeningFailureItem,
} from "../../lib/types";
import { formatDateTime, present } from "../../lib/format";
import { Caption, DataTable, Facts, Note, Section } from "./RunStatusPrimitives";
import { failureReason } from "./runStatusData";

interface FailurePanelProps {
  detail: ScreeningExecutionDetailResponse | null;
  summary: ScreeningExecutionResponse | null;
  loading: boolean;
}

function attemptsFor(detail: ScreeningExecutionDetailResponse | null, noticeId: string): ScreeningAttemptResponse[] {
  return (detail?.attempts ?? []).filter((attempt) => attempt.notice_id === noticeId);
}

/** 관측 수치는 없을 수 있다. 없는 값을 0으로 바꾸지 않는다. */
function metricLabel(value: number | null): string {
  return value === null ? "미측정" : value.toLocaleString("ko-KR");
}

function durationLabel(nanoseconds: number | null): string {
  if (nanoseconds === null) return "미측정";
  return `${(nanoseconds / 1_000_000_000).toFixed(1)}초`;
}

/**
 * 실패 내역 탭.
 *
 * 실행 전체의 실패와 공고 하나의 실패를 구분한다. 서버가 준 안전한 값(공고
 * 식별자 · 실패 단계 · 실패 유형 코드 · 재시도 횟수 · 요약)만 보여 주며 공고
 * 제목·발주기관을 만들어 붙이지 않는다. 내부 경로·자격증명·원문·프롬프트·모델
 * 응답 본문은 표시하지 않는다(docs/security.md).
 */
export function FailurePanel({ detail, summary, loading }: FailurePanelProps) {
  const [selected, setSelected] = useState<ScreeningFailureItem | null>(null);
  const failureCount = detail?.failure_count ?? summary?.failure_count ?? null;
  const failures = detail?.failures ?? [];
  const failureArtifactUrl = detail?.result_urls.failures ?? null;

  return (
    <>
      <Section
        title="실패한 공고"
        action={<Caption as="span">{failureCount === null ? "건수 미확인" : `${failureCount.toLocaleString("ko-KR")}건`}</Caption>}
      >
        {loading && !detail ? <Caption>실패 내역을 불러오는 중입니다.</Caption> : null}
        {failures.length > 0 ? (
          <div>
            {failures.map((failure) => (
              <button
                className="rs-failure-row"
                type="button"
                key={`${failure.notice_id}-${failure.failed_stage}-${failure.retry_count}`}
                onClick={() => setSelected(failure)}
              >
                <span className="rs-cell-stack">
                  <Text as="span" weight="semibold" className="rs-mono">{failure.notice_id}</Text>
                  <Caption as="span">{failure.failed_stage} · 재시도 {failure.retry_count}회 · {failure.status}</Caption>
                  <Text as="span">{failureReason(failure.failure_type)}</Text>
                </span>
                <ChevronRight aria-hidden="true" />
              </button>
            ))}
          </div>
        ) : null}
        {!loading && failures.length === 0 ? (
          <Note title={failureCount === 0 ? "실패한 항목이 없습니다 · 0건" : "건별 실패 내역은 미확인입니다"}>
            {failureCount === 0
              ? "실행이 기록한 실패 건수가 실제로 0입니다."
              : "실패 건수는 기록됐지만 건별 목록을 아직 받지 못했습니다. 0건이 아닙니다."}
          </Note>
        ) : null}
      </Section>

      <Section title="실패 기록 내려받기">
        {failureArtifactUrl ? (
          <div className="rs-link-row">
            <a href={failureArtifactUrl} target="_blank" rel="noreferrer">실패 목록 산출물 열기</a>
          </div>
        ) : (
          <Caption>이 실행에는 내려받을 수 있는 실패 산출물 경로가 없습니다.</Caption>
        )}
        <Note title="실패 기록을 바탕으로 다음 조치를 사람이 판단합니다">
          근거 확인이 필요한 항목과 실행 오류를 구분해 검토합니다. 실패를 자동으로 보정하거나 다시 시작하지
          않습니다.
        </Note>
      </Section>

      <Dialog
        isOpen={selected !== null}
        onOpenChange={(next) => { if (!next) setSelected(null); }}
        purpose="info"
        width={640}
        maxHeight="90dvh"
      >
        <div className="rs-dialog-body" data-astryx-theme="bidops">
          <DialogHeader title="실패 항목 확인" onOpenChange={(next) => { if (!next) setSelected(null); }} />
          {selected ? (
            <div className="rs-dialog-scroll">
              <Facts
                items={[
                  ["공고 식별자", <span className="rs-mono" key="notice">{selected.notice_id}</span>],
                  ["실패 단계", selected.failed_stage],
                  ["실패 유형", <span className="rs-mono" key="type">{selected.failure_type}</span>],
                  ["사유", failureReason(selected.failure_type)],
                  ["재시도", `${selected.retry_count}회`],
                  ["마지막 시도", formatDateTime(selected.last_attempt_at)],
                  ["처리 결과", selected.status],
                  ["이월 검증", selected.failure_context === "carried_over_validation" ? "이월 검증 실패" : "해당 없음"],
                  ["trace", <span className="rs-mono" key="trace">{present(selected.trace_id, "값 없음")}</span>],
                  ["span", <span className="rs-mono" key="span">{present(selected.span_id, "값 없음")}</span>],
                ]}
              />
              <Note title="실행이 남긴 요약" tone="error">{present(selected.error_summary, "서버가 요약을 남기지 않았습니다.")}</Note>
              {attemptsFor(detail, selected.notice_id).length > 0 ? (
                <Section title="이 공고의 시도 기록">
                  <DataTable
                    caption="시도별 상태와 관측 수치"
                    headings={["시도", "단계 · 상태", "입력 / 출력 토큰", "소요"]}
                    rows={attemptsFor(detail, selected.notice_id).map((attempt) => ({
                      id: String(attempt.attempt_id),
                      cells: [
                        `${attempt.attempt_no}회`,
                        <span key="stage">{attempt.stage}<span className="rs-row-sub">{attempt.status === "success" ? "성공" : "실패"}{attempt.failure_type ? ` · ${attempt.failure_type}` : ""}</span></span>,
                        `${metricLabel(attempt.prompt_eval_count)} / ${metricLabel(attempt.eval_count)}`,
                        durationLabel(attempt.total_duration_ns),
                      ],
                    }))}
                  />
                </Section>
              ) : (
                <Caption>이 공고의 시도 기록은 받은 실행 상세에 없습니다.</Caption>
              )}
              <Caption>내부 경로·자격증명·원문·전체 프롬프트와 모델 응답 본문은 화면에 표시하지 않습니다.</Caption>
            </div>
          ) : null}
          <div className="rs-dialog-actions">
            <Button label="확인" onClick={() => setSelected(null)} />
          </div>
        </div>
      </Dialog>
    </>
  );
}

/** 실행 기록 탭의 관측 요약. 값이 없으면 미측정으로 남긴다. */
export function TelemetrySummary({ detail }: { detail: ScreeningExecutionDetailResponse | null }) {
  const attempts = detail?.attempts ?? [];
  const sum = (pick: (attempt: ScreeningAttemptResponse) => number | null): number | null => {
    const values = attempts.map(pick).filter((value): value is number => value !== null);
    return values.length === 0 ? null : values.reduce((total, value) => total + value, 0);
  };
  return (
    <Section title="실행 측정 정보" action={<Caption as="span">받은 시도 {attempts.length}건 기준</Caption>}>
      <Facts
        items={[
          ["모델", present(detail?.model_name, "미확인")],
          ["입력 / 출력 토큰", `${metricLabel(sum((attempt) => attempt.prompt_eval_count))} / ${metricLabel(sum((attempt) => attempt.eval_count))}`],
          ["적재 시간", durationLabel(sum((attempt) => attempt.load_duration_ns))],
          ["총 소요 시간", durationLabel(sum((attempt) => attempt.total_duration_ns))],
        ]}
      />
      <details className="rs-disclosure">
        <summary>모델 식별 해시</summary>
        <code>{present(detail?.model_digest, "값 없음")}</code>
      </details>
      <Caption>
        model_digest · token 수 · duration_ms는 판정 화면의 기본 표시에서 뺐을 뿐 삭제하지 않았습니다.
        감사 목적으로 이 자리에서 확인합니다.
      </Caption>
    </Section>
  );
}
