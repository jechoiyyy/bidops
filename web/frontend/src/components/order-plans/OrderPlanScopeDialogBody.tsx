import { Badge } from "@astryxdesign/core/Badge";
import { Stack } from "@astryxdesign/core/Stack";
import { Text } from "@astryxdesign/core/Text";
import { ReviewStatus } from "../common/ReviewPrimitives";
import type {
  OrderPlanListScope,
  OrderPlanScreeningExecutionSummary,
} from "../../lib/types";
import { formatMoment } from "./orderPlanFormat";
import { scopeLabel, statusDotVariant } from "./orderPlanDialogShared";

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
      {!latest.execution_allowed ? <Badge variant="error" label="정책·모델 연결 비허용" /> : null}
      {active.length ? <Badge variant="warning" label={`진행 중 실행 ${active.length}건`} /> : null}
    </Stack>
  );
}

/** "실행 상태와 표시 규칙" 다이얼로그 본문. 기본 화면에서 큰 설명 영역을 없앤 대신 여기서 읽는다. */
export function OrderPlanScopeDialogBody({
  latestExecution,
  scopedExecutions,
  isCumulative,
  listScope,
  sourceRunId,
}: {
  latestExecution: OrderPlanScreeningExecutionSummary | null;
  scopedExecutions: OrderPlanScreeningExecutionSummary[];
  isCumulative: boolean;
  listScope: OrderPlanListScope | null | undefined;
  sourceRunId: string | null;
}) {
  return (
    <div className="c2l-dialog-body">
      <ExecutionSummaryLine latest={latestExecution} executions={scopedExecutions} />
      <Text type="body" color="secondary" as="p">
        {isCumulative
          ? "BM25 후보 신호와 Qwen relevance 신호를 분리해, 활성화된 적 있는 policy의 운영 실행 결과를 발주계획마다 최신 1건씩 누적해 검토합니다."
          : "BM25 후보 신호와 Qwen relevance 신호를 분리해 선택한 회차의 성공/부분 성공 실행을 검토합니다."} 이 relevance는 tracking state, fitness grade, readiness, 최종 Go/No-Go가 아닙니다.
      </Text>
      <Text type="supporting" color="secondary" as="p">
        <code>filtered_out</code>는 BM25 탈락, <code>not_relevant</code>는 Qwen relevance, <code>unknown</code>은 정보 부족, <code>null</code>은 값 없음/미적용이며 서로 바꾸지 않습니다.
      </Text>
      {/* 기본 화면의 결정 줄에서 뺀 문장. 뜻은 그대로 남기고 자리만 옮겼다. */}
      <Text type="supporting" color="secondary" as="p">
        미선택은 추적 종료가 아닙니다. 추적 선택은 추적 상태만 기록하며 모델 판단·적합성 등급·참여 준비 상태·최종 Go/No-Go를 바꾸지 않습니다.
      </Text>
      {listScope !== undefined ? (
        <Text type="supporting" color="secondary" as="p">목록 범위 · {scopeLabel(listScope)}</Text>
      ) : null}
      {sourceRunId ? (
        <Text type="supporting" color="secondary" as="p">수집 회차 <span className="c2l-digest">{sourceRunId}</span></Text>
      ) : null}
    </div>
  );
}
