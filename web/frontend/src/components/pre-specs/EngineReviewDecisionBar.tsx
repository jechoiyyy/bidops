import { useRef, type ReactNode } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Button } from "@astryxdesign/core/Button";
import { Link } from "react-router-dom";
import { requestActorInput, useRememberedActorName } from "../common/ActorField";
import { DecisionBar } from "../common/ReviewPrimitives";
import { engineReviewErrorCode, engineReviewReason } from "../../lib/engineReviewCopy";
import { engineReviewApi, type EngineReviewState } from "../../lib/engineReviewApi";
import { generateRequestId } from "../../lib/requestId";
import { refreshEngineReview } from "../../lib/useEngineReview";
import { EngineReviewPreviewDialog } from "./EngineReviewPreviewDialog";
import type { useEngineReviewDecision } from "./useEngineReviewDecision";
import "../../styles/engine-review.css";

const STATE_LABELS: Record<EngineReviewState, string> = {
  not_requested: "분석 요청 없음",
  preparing: "분석 준비 중",
  blocked: "분석할 수 없어요",
  awaiting_approval: "분석 승인 대기",
  queued: "분석 대기",
  running: "분석 중",
  result_ready: "결과 확인",
  acknowledged: "결과 읽음",
  stale: "이전 입력 기준",
};

export const ENGINE_TRACKING_START_NOTE = "추적을 시작하면 분석 요청이 함께 올라가요. 자료 전송은 확인한 뒤 따로 승인해요.";

type EngineDecision = ReturnType<typeof useEngineReviewDecision>;

function ReasonText({ reason }: { reason: ReturnType<typeof engineReviewReason> }) {
  return <>{reason.message}{reason.code ? <> <code>{reason.code}</code></> : null}</>;
}

export function EngineReviewReadAction({ noticeId, resultId }: { noticeId: number; resultId: string }) {
  const queryClient = useQueryClient();
  const actor = useRememberedActorName().trim();
  const intent = useRef<{ actor: string; resultId: string; requestId: string } | null>(null);
  const acknowledgment = useMutation({
    mutationFn: (command: NonNullable<typeof intent.current>) =>
      engineReviewApi.acknowledge(noticeId, { result_id: command.resultId, request_id: command.requestId }, command.actor),
    onSuccess: () => refreshEngineReview(queryClient, noticeId),
    onError: (error) => {
      if (engineReviewErrorCode(error) === "input_changed") void refreshEngineReview(queryClient, noticeId);
    },
  });

  function markRead() {
    if (acknowledgment.isPending) return;
    if (!actor) {
      requestActorInput();
      return;
    }
    const previous = intent.current;
    const command = previous?.actor === actor && previous.resultId === resultId
      ? previous : { actor, resultId, requestId: generateRequestId() };
    intent.current = command;
    acknowledgment.mutate(command);
  }

  return (
    <>
      <Button label="읽음으로 표시" size="sm" variant="secondary" isDisabled={acknowledgment.isPending} onClick={markRead} />
      {acknowledgment.isError ? (
        <p className="engine-review-message" role="alert">
          <ReasonText reason={engineReviewReason(engineReviewErrorCode(acknowledgment.error), "읽음으로 표시하지 못했어요.")} />
        </p>
      ) : null}
    </>
  );
}

export function EngineReviewFeedback({ engine }: { engine: EngineDecision }) {
  const failure = engine.requestFailure;
  if (failure) {
    const failedAfterStart = failure.intent?.origin === "tracking_start";
    const reason = engineReviewReason(engineReviewErrorCode(failure.error), "잠시 후 다시 시도해 주세요.");
    return (
      <p className="engine-review-message" role="alert">
        {failedAfterStart ? "추적은 시작했어요. 분석 요청은 올리지 못했어요." : "분석 요청은 올리지 못했어요."}
        {" "}<ReasonText reason={reason} />
      </p>
    );
  }
  return null;
}

export function EngineReviewPreviewActions({ children }: { children: ReactNode }) {
  return <div className="engine-review-preview-actions">{children}</div>;
}

export function EngineReviewDecisionBar({
  engine, variant, start, actorAction, opportunityId,
}: {
  engine: EngineDecision;
  variant: "bar" | "preview";
  start: { action: ReactNode; status: string } | null;
  actorAction: ReactNode;
  opportunityId: number | null;
}) {
  const { view } = engine;
  const state = view?.state;
  const next = view?.next_action;
  const starting = start !== null;
  const label = engine.requestFailure?.intent?.origin === "tracking_start" ? "추적 시작 완료"
    : engine.requestPending ? "분석 요청 중"
    : engine.queryError ? "분석 상태를 확인할 수 없어요"
    : starting ? start.status
    : state ? STATE_LABELS[state] : "분석 상태 확인 중";

  let note: ReactNode;
  let primaryAction: ReactNode;
  let secondaryAction: ReactNode;
  if (engine.requestFailure) {
    secondaryAction = <Button label="분석 요청" variant="secondary" onClick={engine.retryRequest} />;
  } else if (engine.requestPending) {
    note = null;
  } else if (engine.queryError) {
    secondaryAction = <Button label="다시 시도" variant="secondary" onClick={engine.retryQuery} />;
  } else if (starting) {
    primaryAction = start.action;
  } else if (state === "awaiting_approval") {
    if (next === "approve") {
      primaryAction = <Button label="전송 자료 확인" variant="primary" onClick={engine.openPreview} />;
    } else {
      note = "보류 중에는 승인할 수 없어요";
    }
  } else if (state === "preparing" || state === "blocked") {
    note = <ReasonText reason={engineReviewReason(view?.reason ?? null)} />;
  } else if ((state === "not_requested" || state === "stale") && next === "request") {
    secondaryAction = <Button label="분석 요청" variant="secondary" onClick={() => { void engine.requestReview("manual"); }} />;
  } else if ((state === "acknowledged" || state === "not_requested") && variant === "bar" && opportunityId !== null) {
    secondaryAction = <Link className="ps-decision-bar-link" to={`/opportunities/${opportunityId}`}>사업 추적에서 상태 관리 ↗</Link>;
  }

  return (
    <>
      {variant === "preview" && note ? <p className="engine-review-preview-status">{note}</p> : null}
      <DecisionBar
        id={variant === "preview" ? "pre-specs-tracking-target" : undefined}
        className={`engine-review-decision is-${variant}${variant === "preview" ? " pre-specs-detail-actions" : ""}`}
        label="추적 결정"
        stateLabel={starting ? "추적 상태" : "분석 상태"}
        state={{ label, tone: "neutral" }}
        note={variant === "bar" ? note : null}
        actorAction={starting ? actorAction : null}
        secondaryActions={secondaryAction}
        primaryAction={primaryAction}
      />
    </>
  );
}

export function EngineReviewDialog({ engine, noticeId }: { engine: EngineDecision; noticeId: number }) {
  return engine.previewActor === null ? null : (
    <EngineReviewPreviewDialog noticeId={noticeId} actor={engine.previewActor} onClose={engine.closePreview} />
  );
}
