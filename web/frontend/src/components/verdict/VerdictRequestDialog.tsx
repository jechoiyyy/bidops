import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { Button } from "@astryxdesign/core/Button";
import { Dialog, DialogHeader } from "@astryxdesign/core/Dialog";
import { ActorField } from "../common/ActorField";
import { DisabledReason } from "../common/DisabledReason";
import { MutationFeedback } from "../common/MutationFeedback";
import { api } from "../../lib/api";
import { describeVerdictApiError, type ApiErrorDescription } from "../../lib/apiErrors";
import { generateRequestId } from "../../lib/requestId";

/*
 * "다시 판정"(`POST /api/opportunities/{id}/verdict-requests`).
 *
 * 수동 요청은 항상 새 분석 실행이고 이전 판정은 보존된다. 담당자 이름은 기록에 남는 표식이며 인증이
 * 아니다. 요청 식별자는 이 대화상자를 연 때 한 번 만들고, 실패해서 다시 누를 때는 같은 식별자를 쓴다
 * (응답을 잃은 요청이 두 번 접수되지 않게). 서버가 승인·한도·문서 준비 조건으로 막으면 그 안전한 코드의
 * 문구를 그대로 보여 주고 입력은 남긴다. 이 대화상자를 부모가 열 때마다 새로 마운트한다.
 */

interface VerdictRequestDialogProps {
  opportunityId: number;
  onClose: () => void;
  onRequested: () => void;
}

export function VerdictRequestDialog({ opportunityId, onClose, onRequested }: VerdictRequestDialogProps) {
  const [requestId] = useState(generateRequestId);
  const [actorName, setActorName] = useState("");
  const [problem, setProblem] = useState<ApiErrorDescription | null>(null);

  const mutation = useMutation({
    mutationFn: () => api.requestOpportunityVerdict(opportunityId, requestId, actorName.trim()),
    onSuccess: () => {
      setProblem(null);
      onRequested();
    },
    onError: (error: unknown) => setProblem(describeVerdictApiError(error, "판정을 요청하지 못했습니다.")),
  });

  const ready = actorName.trim().length > 0;
  const disabledReason = mutation.isPending
    ? "판정 요청을 접수하고 있습니다."
    : !ready
      ? "판정을 요청하려면 담당자 이름을 입력하십시오."
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
        <DialogHeader onOpenChange={(next) => { if (!next && !mutation.isPending) onClose(); }} title="다시 판정" />
        <p>
          같은 공고 문서와 현재 회사 근거로 새 판정을 요청합니다. 이전 판정은 지워지지 않고 남습니다.
          분석이 끝나면 이 탭에 결과가 보입니다. 판정은 참고 의견이며 추적 여부와 참여 결정은 바뀌지 않습니다.
        </p>
        <ActorField
          autoComplete="off"
          label="요청 기록자"
          onChange={setActorName}
          placeholder="이름 입력"
          required
          value={actorName}
        />
        {problem ? (
          <MutationFeedback problem={problem} tone="error">
            <p>입력한 내용은 그대로 남아 있습니다. 새 판정은 시작되지 않았습니다.</p>
          </MutationFeedback>
        ) : null}
        <div className="opportunity-dialog-actions">
          <Button isDisabled={mutation.isPending} label="취소" onClick={onClose} />
          <Button
            aria-describedby={disabledReason ? "verdict-request-disabled-reason" : undefined}
            isDisabled={!ready || mutation.isPending}
            label={mutation.isPending ? "요청 중…" : "판정 요청"}
            onClick={() => { if (ready && !mutation.isPending) mutation.mutate(); }}
            variant="primary"
          />
        </div>
        {disabledReason ? <DisabledReason id="verdict-request-disabled-reason">{disabledReason}</DisabledReason> : null}
      </div>
    </Dialog>
  );
}
