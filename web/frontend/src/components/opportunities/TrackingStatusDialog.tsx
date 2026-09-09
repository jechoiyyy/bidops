import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Button } from "@astryxdesign/core/Button";
import { Dialog, DialogHeader } from "@astryxdesign/core/Dialog";
import { Selector } from "@astryxdesign/core/Selector";
import { Token } from "@astryxdesign/core/Token";
import { ActorField } from "../common/ActorField";
import { ConfirmDecisionDialog, trackingEndConfirmContent } from "../common/ConfirmDecisionDialog";
import { DisabledReason } from "../common/DisabledReason";
import { MutationFeedback } from "../common/MutationFeedback";
import { api } from "../../lib/api";
import { describeApiError, type ApiErrorDescription } from "../../lib/apiErrors";
import { trackingDescription } from "../../lib/opportunity";
import type { OpportunityDetailResponse, OpportunityTrackingStatus } from "../../lib/types";

/**
 * 추적 상태 변경 (시안의 `추적 상태 변경` 대화상자).
 *
 * 사람이 여기서 고르는 것은 추적 상태 하나다. 적합성 등급·참여 준비 상태·심층
 * 검토 승인·최종 입찰 Go/No-Go를 대신 고르지 않는다. 저장 계약은 이전과 같은
 * `PATCH /opportunities/{id}/tracking-status`이고 담당자 이름은 감사 표식이다.
 *
 * `미선택`은 고를 수 없다. 결정을 되돌려 "아직 아무도 안 골랐다"로 만드는 것은
 * 이력을 지우는 일이지 결정이 아니다. 아직 아무도 고르지 않은 건은 **빈 값으로
 * 열어** 화면이 사람 대신 고르지 않는다.
 */

const SELECTABLE_TRACKING_STATUSES: OpportunityTrackingStatus[] = ["계속 추적", "보류", "종료"];

const REASON_OPTIONS: Record<string, string[]> = {
  "계속 추적": ["사업 범위가 맞아 후속 공고 확인", "추가 문서와 요구사항 확인 필요", "참여 조건 확인 후 재검토", "기타"],
  "보류": ["예산·일정 추가 확인 필요", "참여 조건 확인 필요", "내부 수행 여력 확인 필요", "기타"],
  "종료": ["사업 방향과 맞지 않음", "참여 조건 충족 어려움", "다른 사업에 우선순위 부여", "기타"],
};

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
  const initialStatus: OpportunityTrackingStatus | "" =
    opportunity.tracking_status === "미선택" ? "" : opportunity.tracking_status;
  const [status, setStatus] = useState<OpportunityTrackingStatus | "">(initialStatus);
  const [reason, setReason] = useState("");
  const [custom, setCustom] = useState("");
  const [actorName, setActorName] = useState("");
  const [problem, setProblem] = useState<ApiErrorDescription | null>(null);
  const [discarding, setDiscarding] = useState(false);
  // `종료`만 되돌릴 수 없다. 확인 단계는 native `<dialog>` 바깥에서 열어야 조작할
  // 수 있으므로 이 대화상자를 닫고 확인 단계를 연다. 취소하면 초안 그대로 다시 연다.
  const [endConfirm, setEndConfirm] = useState<ReturnType<typeof trackingEndConfirmContent> | null>(null);

  const validReason = (reason === "기타" ? custom : reason).trim();
  // 기록자 이름은 `ActorField`가 이 브라우저에 기억해 두므로 닫아도 잃지 않는다.
  // 잃는 입력은 고른 상태와 사유뿐이라 이탈 보호도 그 둘만 본다.
  const dirty = status !== initialStatus || reason.length > 0 || custom.length > 0;
  const ready = status !== "" && validReason.length > 0 && actorName.trim().length > 0;

  useEffect(() => {
    onDirtyChange(open && dirty);
    return () => onDirtyChange(false);
  }, [dirty, onDirtyChange, open]);

  const reset = () => {
    setStatus(initialStatus);
    setReason("");
    setCustom("");
    setActorName("");
    setProblem(null);
    setDiscarding(false);
    setEndConfirm(null);
  };

  const mutation = useMutation({
    mutationFn: () =>
      api.updateOpportunityTrackingStatus(
        opportunity.id,
        { tracking_status: status as OpportunityTrackingStatus, reason: validReason },
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
      onSaved("추적 상태를 저장했습니다.");
    },
    onError: (caught: unknown) => {
      setProblem(describeApiError(caught, "추적 상태를 저장하지 못했습니다."));
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

  const submit = () => {
    if (!ready || mutation.isPending) return;
    if (status === "종료") {
      setEndConfirm(trackingEndConfirmContent({
        actor: actorName,
        reason: validReason,
        target: `사업기회 #${opportunity.id} · ${title}`,
      }));
      return;
    }
    mutation.mutate();
  };

  const disabledReason = mutation.isPending
    ? "추적 상태 저장 요청을 처리하고 있습니다."
    : status === ""
      ? "저장하려면 추적 상태를 고르십시오."
      : !validReason
        ? "추적 상태를 저장하려면 선택 사유를 고르거나 직접 입력하십시오."
        : !actorName.trim()
          ? "추적 상태를 저장하려면 결정 기록자를 입력하십시오."
          : null;

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
        width="calc(var(--spacing-12) * 13)"
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
              <Selector
                label="추적 상태"
                onChange={(value) => {
                  setStatus(value as OpportunityTrackingStatus);
                  setReason("");
                  setCustom("");
                }}
                options={SELECTABLE_TRACKING_STATUSES.map((value) => ({
                  value,
                  label: value === "종료" ? "종료 · 추적 종료" : value,
                }))}
                placeholder="상태를 선택하세요"
                value={status}
              />
              <p className="opportunity-caption">
                {status === "" ? "아직 아무도 고르지 않았습니다. 화면이 대신 고르지 않습니다." : trackingDescription(status)}
              </p>
              <Selector
                label="선택 사유"
                onChange={setReason}
                options={REASON_OPTIONS[status] ?? []}
                placeholder="사유를 선택하세요"
                value={reason}
              />
              {reason === "기타" ? (
                <label>
                  <span>선택 사유 직접 입력</span>
                  <input
                    onChange={(event) => setCustom(event.target.value)}
                    placeholder="사유를 직접 입력합니다"
                    value={custom}
                  />
                </label>
              ) : null}
              <ActorField
                autoComplete="off"
                label="결정 기록자"
                onChange={setActorName}
                placeholder="이름 입력"
                required
                value={actorName}
              />
              <p className="opportunity-caption">
                {status === "종료"
                  ? "종료하면 이 사업의 능동 추적을 끝내는 선택으로 기록됩니다. 영구 배제가 아닙니다."
                  : "추적 상태·선택 사유·결정 기록자를 함께 남깁니다."}{" "}
                적합성 등급·참여 준비 상태·심층 검토 승인·최종 입찰 Go/No-Go는 바뀌지 않습니다.
              </p>
              {problem ? (
                <MutationFeedback problem={problem} tone="error">
                  <p>입력한 내용은 그대로 남아 있습니다. 저장된 추적 상태는 바뀌지 않았습니다.</p>
                </MutationFeedback>
              ) : null}
              <div className="opportunity-dialog-actions">
                <Button label="취소" onClick={requestClose} />
                <Button
                  aria-describedby={disabledReason ? "opportunity-tracking-disabled-reason" : undefined}
                  isDisabled={!ready || mutation.isPending}
                  label={mutation.isPending ? "저장 중…" : status === "종료" ? "추적 종료로 변경" : "변경 사항 적용"}
                  onClick={submit}
                  variant="primary"
                />
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
        onConfirm={() => mutation.mutate(undefined, { onSettled: () => setEndConfirm(null) })}
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
