import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Button } from "@astryxdesign/core/Button";
import { Dialog, DialogHeader } from "@astryxdesign/core/Dialog";
import { ConfirmDecisionDialog, trackingEndConfirmContent } from "../common/ConfirmDecisionDialog";
import { DisabledReason } from "../common/DisabledReason";
import {
  TRACKING_SAVE_FAILED,
  TrackingDecisionActions,
  TrackingDecisionInputs,
  TrackingSaveError,
  trackingInputBlockedReason,
  trackingReasonValue,
  trackingSavedMessage,
  type TrackingDecisionStatus,
} from "../common/TrackingDecisionForm";
import { api } from "../../lib/api";
import { describeApiError, type ApiErrorDescription } from "../../lib/apiErrors";
import { trackingDescription } from "../../lib/opportunity";
import type { OpportunityDetailResponse } from "../../lib/types";

/**
 * 추적 상태 변경 (시안의 `추적 상태 변경` 대화상자).
 *
 * 사람이 여기서 고르는 것은 추적 상태 하나다. 적합성 등급·참여 준비 상태·심층
 * 검토 승인·최종 입찰 Go/No-Go를 대신 고르지 않는다. 저장 계약은 이전과 같은
 * `PATCH /opportunities/{id}/tracking-status`이고 담당자 이름은 감사 표식이다.
 *
 * 입력·검증·버튼·저장 결과는 추적 결정 입력 한 벌(`TrackingDecisionForm`, C-7)과 같다 — 발주계획
 * 상세 바닥·사전규격과 같은 필드(선택 사유 → 직접 입력 → 담당자 이름), 같은 결정 버튼(`추적 시작`/
 * `계속 추적` · `보류` · `추적 종료`), 같은 실패 표시(입력 옆)와 같은 성공 문장(화면 알림). 상태를
 * 먼저 고르는 드롭다운은 없고 결정 버튼이 곧 고르는 상태다. 그래서 화면이 사람 대신 상태를 미리
 * 고르는 일이 없다.
 *
 * `미선택`은 고를 수 없다. 결정을 되돌려 "아직 아무도 안 골랐다"로 만드는 것은
 * 이력을 지우는 일이지 결정이 아니다(`추적 되돌리기`가 따로 있다).
 */

/** 사유 예시. 세 상태의 옛 예시를 한 목록으로 모았다(결정 버튼이 마지막에 오므로 상태별로 나누지 않는다). */
const OPPORTUNITY_TRACKING_REASONS = [
  "사업 범위가 맞아 후속 공고 확인",
  "추가 문서와 요구사항 확인 필요",
  "참여 조건 확인 후 재검토",
  "예산·일정 추가 확인 필요",
  "참여 조건 확인 필요",
  "내부 수행 여력 확인 필요",
  "사업 방향과 맞지 않음",
  "참여 조건 충족 어려움",
  "다른 사업에 우선순위 부여",
] as const;

export interface TrackingStatusDialogProps {
  opportunity: OpportunityDetailResponse;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSaved: (message: string) => void;
  /** 저장하지 않은 입력이 남아 있는지 페이지 이탈 보호에 알린다. */
  onDirtyChange: (dirty: boolean) => void;
  title: string;
}

export function TrackingStatusDialog({
  onDirtyChange,
  onOpenChange,
  onSaved,
  open,
  opportunity,
  title,
}: TrackingStatusDialogProps) {
  const queryClient = useQueryClient();
  const [choice, setChoice] = useState("");
  const [custom, setCustom] = useState("");
  const [actorName, setActorName] = useState("");
  const [problem, setProblem] = useState<ApiErrorDescription | null>(null);
  const [discarding, setDiscarding] = useState(false);
  // `종료`만 되돌릴 수 없다. 확인 단계는 native `<dialog>` 바깥에서 열어야 조작할
  // 수 있으므로 이 대화상자를 닫고 확인 단계를 연다. 취소하면 초안 그대로 다시 연다.
  const [endConfirm, setEndConfirm] = useState<ReturnType<typeof trackingEndConfirmContent> | null>(null);

  const reason = trackingReasonValue(choice, custom);
  // 기록자 이름은 `ActorField`가 이 브라우저에 기억해 두므로 닫아도 잃지 않는다.
  // 잃는 입력은 사유뿐이라 이탈 보호도 그것만 본다.
  const dirty = choice !== "" || custom.length > 0;

  useEffect(() => {
    onDirtyChange(open && dirty);
    return () => onDirtyChange(false);
  }, [dirty, onDirtyChange, open]);

  const reset = () => {
    setChoice("");
    setCustom("");
    setActorName("");
    setProblem(null);
    setDiscarding(false);
    setEndConfirm(null);
  };

  const mutation = useMutation({
    mutationFn: (status: TrackingDecisionStatus) =>
      api.updateOpportunityTrackingStatus(
        opportunity.id,
        { tracking_status: status, reason },
        actorName,
      ),
    onSuccess: async (saved) => {
      // 성공하면 초안을 비운다. 실패하면 아래 onError가 초안을 그대로 둔다.
      reset();
      onDirtyChange(false);
      onOpenChange(false);
      queryClient.setQueryData(["opportunity", opportunity.id], saved);
      await queryClient.invalidateQueries({ queryKey: ["opportunities"] });
      await queryClient.invalidateQueries({ queryKey: ["opportunity-tracking-decisions", opportunity.id] });
      onSaved(trackingSavedMessage(saved.tracking_status));
    },
    onError: (caught: unknown) => {
      setProblem(describeApiError(caught, TRACKING_SAVE_FAILED));
    },
  });

  const requestClose = () => {
    if (dirty) {
      setDiscarding(true);
      return;
    }
    reset();
    onOpenChange(false);
  };

  const disabledReason = trackingInputBlockedReason({ choice, custom, actorName, pending: mutation.isPending });

  const decide = (status: TrackingDecisionStatus) => {
    if (disabledReason !== null) return;
    if (status === "종료") {
      setEndConfirm(trackingEndConfirmContent({
        actor: actorName,
        reason,
        target: `사업기회 #${opportunity.id} · ${title}`,
      }));
      return;
    }
    mutation.mutate(status);
  };

  return (
    <>
      <Dialog
        isOpen={open && endConfirm === null}
        maxHeight="90dvh"
        onOpenChange={(next) => {
          if (!next && endConfirm === null) requestClose();
        }}
        padding={6}
        purpose="form"
        width="624px"
      >
        <div className="opportunity-dialog-body">
          <DialogHeader
            title={discarding ? "입력한 내용을 버릴까요?" : "추적 상태 변경"}
            onOpenChange={(next) => {
              if (!next) requestClose();
            }}
          />
          {discarding ? (
            <>
              <p>저장하지 않은 입력이 있습니다. 닫으면 입력한 내용이 사라지며 저장된 추적 상태는 바뀌지 않습니다.</p>
              <div className="opportunity-dialog-actions">
                <Button label="계속 작성" onClick={() => setDiscarding(false)} />
                <Button
                  label="입력 버리고 닫기"
                  onClick={() => {
                    reset();
                    onOpenChange(false);
                  }}
                />
              </div>
            </>
          ) : (
            <>
              <p className="opportunity-dialog-target"><strong>{title}</strong></p>
              <p className="opportunity-caption">
                현재 추적 상태 · {opportunity.tracking_status} — {opportunity.tracking_status === "미선택"
                  ? "아직 아무도 고르지 않았습니다. 화면이 대신 고르지 않습니다."
                  : trackingDescription(opportunity.tracking_status)}
              </p>
              <TrackingDecisionInputs
                presets={OPPORTUNITY_TRACKING_REASONS}
                choice={choice}
                onChoiceChange={setChoice}
                custom={custom}
                onCustomChange={setCustom}
                actorName={actorName}
                onActorNameChange={setActorName}
                isDisabled={mutation.isPending}
                size="md"
              />
              <p className="opportunity-caption">
                추적 상태·선택 사유·담당자 이름을 함께 남깁니다. 추적 종료는 능동 추적을 끝내는 선택이며 영구 배제가 아닙니다.{" "}
                적합성 등급·참여 준비 상태·심층 검토 승인·최종 입찰 Go/No-Go는 바뀌지 않습니다.
              </p>
              {/* 추적 상태 저장은 재검토 신호를 해제한다(spec §6.2). 따로 확인할 필요가 없음을 먼저 알린다. */}
              {opportunity.recheck_signal ? (
                <p className="opportunity-caption opportunity-tracking-signal-note">저장하면 새 공고 확인도 함께 처리됩니다.</p>
              ) : null}
              {problem ? <TrackingSaveError problem={problem} /> : null}
              <div className="opportunity-dialog-actions">
                <TrackingDecisionActions
                  statuses={["계속 추적", "보류", "종료"]}
                  current={opportunity.tracking_status}
                  disabledReasonId="opportunity-tracking-disabled-reason"
                  isDisabled={disabledReason !== null}
                  pendingStatus={mutation.isPending ? (mutation.variables ?? null) : null}
                  onDecide={decide}
                />
                <Button label="취소" onClick={requestClose} />
              </div>
              {disabledReason ? (
                <DisabledReason id="opportunity-tracking-disabled-reason">{disabledReason}</DisabledReason>
              ) : null}
            </>
          )}
        </div>
      </Dialog>

      {/* 확인 단계. 취소하면 초안은 그대로 남고 요청은 나가지 않는다. */}
      <ConfirmDecisionDialog
        confirmLabel={endConfirm?.confirmLabel ?? "종료 상태로 저장"}
        isPending={mutation.isPending}
        onConfirm={() => mutation.mutate("종료", { onSettled: () => setEndConfirm(null) })}
        onOpenChange={(next) => {
          if (!next) setEndConfirm(null);
        }}
        open={endConfirm !== null}
        summary={endConfirm?.summary ?? []}
        title={endConfirm?.title ?? "추적을 종료합니다"}
      />
    </>
  );
}
