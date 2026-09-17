import { useEffect, useId, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Button } from "@astryxdesign/core/Button";
import { ActorField } from "../common/ActorField";
import { DisabledReason } from "../common/DisabledReason";
import { MutationFeedback } from "../common/MutationFeedback";
import { ApiError, api } from "../../lib/api";
import { describeApiError, type ApiErrorDescription } from "../../lib/apiErrors";
import type { OpportunityDetailResponse } from "../../lib/types";

/**
 * 새 공고 재검토 신호의 `확인 완료` (spec §6.2).
 *
 * 사람이 **지금 보고 있는 근거 연결**(`recheck_signal_link_id`)을 함께 보내므로, 그사이
 * 근거가 바뀌었으면 서버가 409 `recheck_signal_changed`로 거절한다. 그때는 최신 상태를
 * 다시 읽는다고 알리고 다시 읽는다. 확인 완료는 신호만 해제하며 추적 상태·적합성 등급·
 * 최종 Go/No-Go를 바꾸지 않는다. 메모는 선택이고 이력에는 메모가 있었는지만 남는다.
 */

export const RECHECK_NOTE_MAX = 500;

export interface RecheckAcknowledgementProps {
  opportunity: OpportunityDetailResponse;
  onDirtyChange: (dirty: boolean) => void;
  onSaved: (message: string) => void;
  /** 신호가 바뀌었거나 이미 없어 최신 상태를 다시 읽을 때 상세가 남길 안내. */
  onStale: (message: string) => void;
}

export function RecheckAcknowledgement({ onDirtyChange, onSaved, onStale, opportunity }: RecheckAcknowledgementProps) {
  const queryClient = useQueryClient();
  const noteId = useId();
  const [note, setNote] = useState("");
  const [actorName, setActorName] = useState("");
  const [problem, setProblem] = useState<ApiErrorDescription | null>(null);
  const expectedLinkId = opportunity.recheck_signal_link_id;
  const trimmedNote = note.trim();

  useEffect(() => {
    onDirtyChange(note.length > 0);
    return () => onDirtyChange(false);
  }, [note, onDirtyChange]);

  const refresh = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["opportunity", opportunity.id] }),
      queryClient.invalidateQueries({ queryKey: ["opportunities"] }),
      queryClient.invalidateQueries({ queryKey: ["opportunity-tracking-decisions", opportunity.id] }),
    ]);
  };

  const mutation = useMutation({
    mutationFn: (linkId: number) =>
      api.acknowledgeRecheckSignal(
        opportunity.id,
        trimmedNote ? { expected_link_id: linkId, note: trimmedNote } : { expected_link_id: linkId },
        actorName,
      ),
    onSuccess: async (saved) => {
      setNote("");
      setProblem(null);
      onDirtyChange(false);
      queryClient.setQueryData(["opportunity", opportunity.id], saved);
      await refresh();
      onSaved("새 공고 확인을 기록했습니다. 추적 상태는 바뀌지 않았습니다.");
    },
    onError: async (caught: unknown) => {
      // 오류는 안정 코드로만 가른다(서버 문구로 가르지 않는다).
      if (caught instanceof ApiError && caught.code === "recheck_signal_changed") {
        setProblem(null);
        onStale("새 공고 근거가 바뀌었습니다. 최신 상태를 다시 읽습니다.");
        await refresh();
        return;
      }
      if (caught instanceof ApiError && caught.code === "recheck_signal_absent") {
        setProblem(null);
        onStale("확인할 재검토 신호가 이미 없습니다. 최신 상태를 다시 읽습니다.");
        await refresh();
        return;
      }
      setProblem(describeApiError(caught, "새 공고 확인을 저장하지 못했습니다."));
    },
  });

  const disabledReason = mutation.isPending
    ? "새 공고 확인을 저장하고 있습니다."
    : expectedLinkId === null
      ? "근거 연결 식별자가 없어 확인 처리할 수 없습니다. 최신 상태를 다시 읽어 주십시오."
      : !actorName.trim()
        ? "확인 완료를 기록하려면 결정 기록자를 입력하십시오."
        : null;
  const disabledId = `${noteId}-disabled`;

  return (
    <div className="opportunity-ack-form">
      <label htmlFor={noteId}>
        <span>확인 메모 (선택 · {note.length}/{RECHECK_NOTE_MAX}자)</span>
        <textarea
          id={noteId}
          maxLength={RECHECK_NOTE_MAX}
          onChange={(event) => setNote(event.target.value)}
          placeholder="확인한 내용을 남길 수 있습니다. 이력에는 메모가 있었는지만 표시됩니다."
          rows={2}
          value={note}
        />
      </label>
      <ActorField
        autoComplete="off"
        label="결정 기록자"
        onChange={setActorName}
        placeholder="이름 입력"
        required
        value={actorName}
      />
      {problem ? (
        <MutationFeedback problem={problem} tone="error">
          <p>재검토 신호는 그대로 남아 있습니다. 입력한 메모도 그대로입니다.</p>
        </MutationFeedback>
      ) : null}
      <div className="opportunity-check-actions">
        <Button
          aria-describedby={disabledReason ? disabledId : undefined}
          isDisabled={disabledReason !== null}
          label={mutation.isPending ? "저장 중…" : "확인 완료"}
          onClick={() => {
            if (disabledReason === null && expectedLinkId !== null) mutation.mutate(expectedLinkId);
          }}
          size="sm"
          variant="primary"
        />
        <p className="opportunity-caption">신호만 해제합니다. 추적 상태·최종 Go/No-Go는 바뀌지 않습니다.</p>
      </div>
      {disabledReason ? <DisabledReason id={disabledId}>{disabledReason}</DisabledReason> : null}
    </div>
  );
}
