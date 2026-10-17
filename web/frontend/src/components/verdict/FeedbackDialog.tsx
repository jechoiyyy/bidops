import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { Button } from "@astryxdesign/core/Button";
import { Dialog, DialogHeader } from "@astryxdesign/core/Dialog";
import { Selector } from "@astryxdesign/core/Selector";
import { TextArea } from "@astryxdesign/core/TextArea";
import { ActorField } from "../common/ActorField";
import { DisabledReason } from "../common/DisabledReason";
import { MutationFeedback } from "../common/MutationFeedback";
import { api } from "../../lib/api";
import { describeVerdictApiError, type ApiErrorDescription } from "../../lib/apiErrors";
import { generateRequestId } from "../../lib/requestId";
import type { VerdictFeedbackKind } from "../../lib/types";
import { FEEDBACK_KIND_LABEL } from "../../lib/verdict";

/*
 * 판정 오류 제보(`POST /api/companies/{company_id}/pre-specs/{notice_id}/verdict-feedback`).
 *
 * 제보는 append-only 기록이며 판정·추적·최종 Go/No-Go를 바꾸지 않는다. 판정 전체를 가리키면
 * (`wrong_verdict`) 유형이 하나뿐이고, 요구사항 한 행에서 열면 그 행에 쓸 수 있는 세 유형 중에 고른다.
 * 요구사항 식별자(원문 hash를 포함할 수 있다)는 화면에 그리지 않고 요청에만 싣는다. 메모는 500자까지다.
 * 요청 식별자는 대화상자를 연 때 한 번 만들고 실패 뒤 재시도에는 같은 값을 쓴다.
 */

export const FEEDBACK_NOTE_MAX = 500;

const UNIT_KINDS: VerdictFeedbackKind[] = ["wrong_unit", "not_requirement", "source_mismatch"];

interface FeedbackDialogProps {
  companyId: string;
  noticeId: number;
  attemptId: string;
  /** 요구사항 한 행에서 열었으면 그 행의 식별자와 안내 문장. 판정 전체 제보면 `null`이다. */
  unit: { unitId: string; requirement: string } | null;
  initialKind: VerdictFeedbackKind;
  onClose: () => void;
  onSaved: () => void;
}

export function FeedbackDialog({ companyId, noticeId, attemptId, unit, initialKind, onClose, onSaved }: FeedbackDialogProps) {
  const [requestId] = useState(generateRequestId);
  const [kind, setKind] = useState<VerdictFeedbackKind>(unit ? initialKind : "wrong_verdict");
  const [note, setNote] = useState("");
  const [actorName, setActorName] = useState("");
  const [problem, setProblem] = useState<ApiErrorDescription | null>(null);

  const mutation = useMutation({
    mutationFn: () =>
      api.createVerdictFeedback(
        companyId,
        noticeId,
        {
          attempt_id: attemptId,
          kind,
          ...(unit ? { unit_id: unit.unitId } : {}),
          ...(note.trim() ? { note: note.trim() } : {}),
          request_id: requestId,
        },
        actorName.trim(),
      ),
    onSuccess: () => {
      setProblem(null);
      onSaved();
    },
    onError: (error: unknown) => setProblem(describeVerdictApiError(error, "오류 제보를 저장하지 못했습니다.")),
  });

  const ready = actorName.trim().length > 0 && note.length <= FEEDBACK_NOTE_MAX;
  const disabledReason = mutation.isPending
    ? "오류 제보를 저장하고 있습니다."
    : actorName.trim().length === 0
      ? "제보하려면 담당자 이름을 입력하십시오."
      : null;

  return (
    <Dialog
      isOpen
      maxHeight="90dvh"
      onOpenChange={(next) => { if (!next && !mutation.isPending) onClose(); }}
      padding={6}
      purpose="form"
      width="calc(var(--spacing-12) * 13)"
    >
      <div className="opportunity-dialog-body">
        <DialogHeader onOpenChange={(next) => { if (!next && !mutation.isPending) onClose(); }} title="판정 오류 제보" />
        {unit ? (
          <>
            <p className="vd-feedback-target">{unit.requirement}</p>
            <Selector
              label="제보 유형"
              onChange={(value) => setKind(value as VerdictFeedbackKind)}
              options={UNIT_KINDS.map((value) => ({ value, label: FEEDBACK_KIND_LABEL[value] }))}
              value={kind}
            />
          </>
        ) : (
          <p>이 판정 전체가 틀렸다고 제보합니다.</p>
        )}
        <TextArea
          label="메모 (선택)"
          maxLength={FEEDBACK_NOTE_MAX}
          onChange={setNote}
          placeholder="어느 부분이 왜 틀렸는지 적어 주세요"
          rows={3}
          value={note}
        />
        <p className="opportunity-caption">{note.length} / {FEEDBACK_NOTE_MAX}자</p>
        <ActorField
          autoComplete="off"
          label="제보 기록자"
          onChange={setActorName}
          placeholder="이름 입력"
          required
          value={actorName}
        />
        <p className="opportunity-caption">제보는 기록으로만 남고 판정·추적 결정·최종 Go/No-Go를 바꾸지 않습니다.</p>
        {problem ? (
          <MutationFeedback problem={problem} tone="error">
            <p>입력한 내용은 그대로 남아 있습니다. 제보는 저장되지 않았습니다.</p>
          </MutationFeedback>
        ) : null}
        <div className="opportunity-dialog-actions">
          <Button isDisabled={mutation.isPending} label="취소" onClick={onClose} />
          <Button
            aria-describedby={disabledReason ? "verdict-feedback-disabled-reason" : undefined}
            isDisabled={!ready || mutation.isPending}
            label={mutation.isPending ? "저장 중…" : "제보 보내기"}
            onClick={() => { if (ready && !mutation.isPending) mutation.mutate(); }}
            variant="primary"
          />
        </div>
        {disabledReason ? <DisabledReason id="verdict-feedback-disabled-reason">{disabledReason}</DisabledReason> : null}
      </div>
    </Dialog>
  );
}
