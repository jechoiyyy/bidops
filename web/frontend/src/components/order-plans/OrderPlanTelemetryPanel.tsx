import { Badge } from "@astryxdesign/core/Badge";
import { Heading } from "@astryxdesign/core/Heading";
import { Stack } from "@astryxdesign/core/Stack";
import { Text } from "@astryxdesign/core/Text";
import type {
  OrderPlanScreeningExecutionDetailResponse,
  OrderPlanScreeningExecutionSummary,
} from "../../lib/types";
import { formatMoment, textOrUnknown } from "./orderPlanFormat";
import { statusTone } from "./orderPlanDialogShared";

function formatNumber(value: number | null | undefined): string {
  return value === null || value === undefined ? "null (미측정)" : value.toLocaleString("ko-KR");
}

function formatNullableMoment(value: string | null): string {
  return value === null ? "null" : formatMoment(value);
}

/** model_digest·token 수·duration_ms·binding sha256·artifact 요약. 삭제하지 않고 이 탭으로 옮겼다. */
export function OrderPlanTelemetryPanel({
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
          <Text type="body" color="secondary">{execution.execution_allowed ? "정책·모델 연결 허용" : "정책·모델 연결 비허용"}</Text>
        </Stack>
      </div>

      <dl className="c2l-fact-grid">
        <div><dt>execution_id</dt><dd className="c2l-digest">{execution.execution_id}</dd></div>
        <div><dt>요청자</dt><dd>{textOrUnknown(execution.requested_by)}</dd></div>
        <div><dt>policy version</dt><dd>{execution.policy_version}</dd></div>
        <div><dt>population</dt><dd>{formatNumber(execution.population_count)}건</dd></div>
        <div><dt>대상 hash</dt><dd className="c2l-digest">{execution.population_sha256}</dd></div>
        <div><dt>정책 해시</dt><dd className="c2l-digest">{execution.policy_sha256}</dd></div>
        <div><dt>모델 연결 상태</dt><dd>{execution.execution_allowed ? "허용됨" : "허용됨이 아님"}</dd></div>
        <div><dt>모델 연결 해시</dt><dd className="c2l-digest">{execution.binding_sha256}</dd></div>
      </dl>

      <dl className="c2l-fact-grid" aria-label="단계별 모델 연결">
        <div><dt>BM25 모델 연결</dt><dd>{execution.stage1_binding_version} · <span className="c2l-digest">{execution.stage1_binding_sha256}</span></dd></div>
        <div><dt>Qwen 모델 연결</dt><dd>{execution.stage2_binding_version} · <span className="c2l-digest">{execution.stage2_binding_sha256}</span></dd></div>
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
        <Heading level={5}>실행 모델 · 수정본 · 프롬프트 · 프로필 · 분석 회차</Heading>
        {detailPending ? <Text type="body" color="secondary" as="p">실행 artifact 요약을 불러오는 중…</Text> : null}
        {detailError ? <Text type="body" color="secondary" as="p" data-role="alert">실행 상세를 불러오지 못해 산출물·분석 회차 요약을 확인할 수 없습니다.</Text> : null}
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
        ) : detail ? <Text type="body" color="secondary" as="p">분석 회차 기록 없음 (서버 응답)</Text> : null}
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
