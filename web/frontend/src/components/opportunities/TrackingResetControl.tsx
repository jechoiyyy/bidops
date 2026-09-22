import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Button } from "@astryxdesign/core/Button";
import { ActorField } from "../common/ActorField";
import { DisabledReason } from "../common/DisabledReason";
import { MutationFeedback } from "../common/MutationFeedback";
import { api } from "../../lib/api";
import { describeApiError, type ApiErrorDescription } from "../../lib/apiErrors";
import type { OpportunityTrackingStatus } from "../../lib/types";
import { TRACKING_RESET_LABEL } from "./trackingFlow";

/**
 * 추적 결정을 `미선택`으로 되돌리는 단추와 그 확인 입력(ADR-0028 개정, ADR-0068).
 *
 * 병합이 막혔을 때 한쪽의 결정을 정리하는 유일한 출구이고, 사업 추적 상세의
 * 추적 결정 카드에서 잘못 고른 결정을 되돌리는 자리이기도 하다. 저장 계약은
 * 추적 상태 변경과 **같은** `PATCH /opportunities/{id}/tracking-status`이며
 * `tracking_status: "미선택"`·사유·담당자를 모두 보낸다 — 되돌리기도 감사
 * 기록이 남는 사람의 결정이다.
 *
 * 되돌린 뒤 무엇을 안내할지는 부르는 화면이 정한다(`onReset`). 이 컴포넌트는
 * 후보 수락 같은 다음 행동을 **자동으로 다시 시도하지 않는다.** 두 번째 결정도
 * 사람이 명시적으로 한다.
 *
 * `미선택` row에는 사유·선택자·시각이 남지 않는다(DB CHECK). 사라지는 것이
 * 아니라 감사 이벤트로 옮겨 간다는 사실을 화면이 그대로 말한다.
 */

export interface TrackingResetControlProps {
  opportunityId: number;
  /** 지금 저장된 추적 상태. `미선택`이면 되돌릴 결정이 없다. */
  currentStatus: OpportunityTrackingStatus;
  /**
   * 이미 담당자 이름을 받은 화면(후보 연결 확인 대화상자)은 그 값을 넘겨 같은
   * 입력을 두 번 받지 않는다. 넘기지 않으면 자기 입력을 그린다.
   */
  actorName?: string;
  /** 단추 문구. 목록 안에서는 어느 사업인지 이름만으로 드러나야 한다. */
  label?: string;
  /** 확인 입력에 덧붙일 한 문장. 되돌린 뒤 무엇이 일어나지 않는지를 적는다. */
  note?: string;
  /** 되돌리기에 성공한 뒤. 안내 문구는 부르는 화면이 소유한다. */
  onReset: () => void;
}

export function TrackingResetControl({
  actorName,
  currentStatus,
  label = TRACKING_RESET_LABEL,
  note,
  onReset,
  opportunityId,
}: TrackingResetControlProps) {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState("");
  const [ownActor, setOwnActor] = useState("");
  const [problem, setProblem] = useState<ApiErrorDescription | null>(null);

  const actor = (actorName ?? ownActor).trim();
  const validReason = reason.trim();
  const ready = validReason.length > 0 && actor.length > 0;
  const alreadyUnselected = currentStatus === "미선택";
  const reasonId = `tracking-reset-reason-${opportunityId}`;
  const disabledId = `tracking-reset-disabled-${opportunityId}`;

  const close = () => {
    setOpen(false);
    setReason("");
    setProblem(null);
  };

  const mutation = useMutation({
    mutationFn: () =>
      api.updateOpportunityTrackingStatus(
        opportunityId,
        { tracking_status: "미선택", reason: validReason },
        actor,
      ),
    onSuccess: async () => {
      close();
      // 되돌린 사업은 이 화면이 보고 있는 사업이 아닐 수 있다(병합 막힘 안내).
      // 사업기회를 읽는 query는 모두 다시 읽는다.
      await queryClient.invalidateQueries({ queryKey: ["opportunity"] });
      await queryClient.invalidateQueries({ queryKey: ["opportunities"] });
      await queryClient.invalidateQueries({ queryKey: ["opportunity-tracking-decisions"] });
      onReset();
    },
    onError: (caught: unknown) => {
      setProblem(describeApiError(caught, "추적 결정을 되돌리지 못했습니다."));
    },
  });

  if (!open) {
    return (
      <div className="opportunity-tracking-reset">
        <Button
          aria-describedby={alreadyUnselected ? disabledId : undefined}
          isDisabled={alreadyUnselected}
          label={label}
          onClick={() => setOpen(true)}
          size="sm"
        />
        {alreadyUnselected ? (
          <DisabledReason id={disabledId}>
            이미 미선택입니다. 되돌릴 추적 결정이 없습니다.
          </DisabledReason>
        ) : null}
      </div>
    );
  }

  const disabledReason = mutation.isPending
    ? "되돌리기 요청을 처리하고 있습니다."
    : !validReason
      ? "되돌리려면 되돌리는 이유를 입력하십시오."
      : !actor
        ? "되돌리려면 결정 기록자를 입력하십시오."
        : null;

  return (
    <div className="opportunity-tracking-reset opportunity-tracking-reset-open">
      <p>
        저장된 추적 결정(<strong>{currentStatus}</strong>)을 미선택으로 되돌립니다. 되돌리면 이 사업은
        아직 아무도 고르지 않은 상태가 되어 검토할 항목·조치 필요로 돌아옵니다.
      </p>
      <p className="opportunity-caption">
        지금 행의 사유·선택자·시각은 비워지지만 사라지지 않습니다 — 되돌린 기록은 추적 이력의 감사
        이벤트에 남습니다.
      </p>
      {note ? <p className="opportunity-caption">{note}</p> : null}
      <label htmlFor={reasonId}>
        <span>되돌리는 이유</span>
        <input
          id={reasonId}
          maxLength={500}
          onChange={(event) => setReason(event.target.value)}
          placeholder="되돌리는 이유를 입력합니다"
          value={reason}
        />
      </label>
      {actorName === undefined ? (
        <ActorField
          autoComplete="off"
          label="결정 기록자"
          onChange={setOwnActor}
          placeholder="이름 입력"
          required
          value={ownActor}
        />
      ) : (
        <p className="opportunity-caption">
          결정 기록자 · {actor || "미입력"} · 감사 표식이며 신원 인증이 아닙니다.
        </p>
      )}
      {problem ? (
        <MutationFeedback problem={problem} tone="error">
          <p>추적 결정은 바뀌지 않았습니다. 입력한 내용은 그대로 남아 있습니다.</p>
        </MutationFeedback>
      ) : null}
      <div className="opportunity-tracking-reset-actions">
        <Button isDisabled={mutation.isPending} label="취소" onClick={close} size="sm" />
        <Button
          aria-describedby={disabledReason ? disabledId : undefined}
          isDisabled={!ready || mutation.isPending}
          label={mutation.isPending ? "되돌리는 중…" : `${TRACKING_RESET_LABEL} 실행`}
          onClick={() => {
            if (ready && !mutation.isPending) mutation.mutate();
          }}
          variant="primary"
        />
      </div>
      {disabledReason ? <DisabledReason id={disabledId}>{disabledReason}</DisabledReason> : null}
    </div>
  );
}
